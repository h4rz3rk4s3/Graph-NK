"""
Annotator Worker — fan-out coordinator (Milestones 4–8).

Consumes TextUnit events from stream_units, runs all registered annotators,
and publishes each Signal to stream_signals.

Architecture:
  - Annotators are registered in ANNOTATORS list at the bottom of this module.
  - The ClassifierAnnotator uses batch_annotate() for throughput; all others
    are called one unit at a time (CPU-bound, fast enough at research scale).
  - No annotator error can block the others — each is wrapped in try/except
    and failures are logged with enough context to reproduce.

See FRAMEWORK_DESIGN.md §3.1 (fan-out rationale); BUILD_SPEC.md §6 M4–M8.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import defaultdict, deque
from typing import Any

from annotators.base import Signal, TextUnit
from broker import get_broker
from progress import Progress
from settings import settings

logger = logging.getLogger(__name__)


def _load_annotators(nlp, strict: bool = False) -> list[Any]:
    """
    Instantiate all annotators against a single shared spaCy pipeline `nlp`.
    Rule annotators build their matchers from nlp.vocab and operate on the
    pre-parsed Doc the worker supplies — the text is parsed once per unit.
    ClassifierAnnotator is excluded if no model path is configured.

    `strict` (CHANGELOG 2026-08-27): incremental mode requires the FULL expected
    annotator set. If any rule annotator fails to load (e.g. a malformed
    lexicon) or the classifier is missing, raise instead of silently continuing
    — otherwise units get a ClassifierVerdict (and drop out of the un-annotated
    selection) while never having been annotated by the failed rule. Non-strict
    callers (bench) keep the tolerant skip-and-log behaviour.
    """
    annotators = []

    def _load(name: str, module: str, cls: str) -> Any | None:
        try:
            import importlib

            annotator_class = getattr(importlib.import_module(module), cls)
            return annotator_class(nlp)
        except Exception as exc:
            if strict:
                raise RuntimeError(
                    f"Failed to load {name}; --only-unannotated requires the full "
                    f"annotator set, otherwise units get a completion verdict "
                    f"without ever being fully annotated: {exc}"
                ) from exc
            logger.error("Could not load %s: %s", name, exc)
            return None

    if ann := _load("LexiconAnnotator", "annotators.lexical", "LexiconAnnotator"):
        annotators.append(ann)

    if ann := _load("SpacyMorphoAnnotator", "annotators.morpho_syntactic", "SpacyMorphoAnnotator"):
        annotators.append(ann)

    if ann := _load("AffixAnnotator", "annotators.word_formation", "AffixAnnotator"):
        annotators.append(ann)

    if ann := _load("RhetoricalAnnotator", "annotators.rhetorical", "RhetoricalAnnotator"):
        annotators.append(ann)

    try:
        import os

        from annotators.classifier import ClassifierAnnotator

        if os.path.isdir(settings.classifier_model_path):
            annotators.append(ClassifierAnnotator())
        elif strict:
            raise RuntimeError(
                "Classifier model not found at "
                f"{settings.classifier_model_path!r}; --only-unannotated requires "
                "it, because its ClassifierVerdict is the completion marker "
                "incremental mode relies on."
            )
        else:
            logger.warning(
                "Classifier model not found at '%s'. Skipping ClassifierAnnotator.",
                settings.classifier_model_path,
            )
    except Exception as exc:
        if strict:
            raise RuntimeError(f"Failed to load ClassifierAnnotator: {exc}") from exc
        logger.error("Could not load ClassifierAnnotator: %s", exc)

    logger.info("Annotator worker: %d annotators loaded.", len(annotators))
    return annotators


def _hwm_key(id_lo: str | None, id_hi: str | None, only_unannotated: bool = False) -> str:
    """Redis key for one shard range and annotation configuration.

    TextUnit ids contain colons, so concatenating bounds is not injective. A
    canonical JSON hash also prevents a checkpoint from being reused after a
    scope, rule set, or classifier change. `only_unannotated` is part of the
    identity so an incremental run can never clobber a full-run HWM (and vice
    versa) for the same bounds (CHANGELOG 2026-08-27).
    """
    identity = {
        "id_lo": id_lo,
        "id_hi": id_hi,
        "languages": settings.annotate_languages,
        "min_tokens": settings.annotate_min_tokens,
        "roles": settings.annotate_roles,
        "parent_types": settings.annotate_parent_types,
        "skip_bots": settings.annotate_skip_bots,
        "only_referenced_prs": settings.annotate_only_referenced_prs,
        "max_chars": settings.annotate_max_chars,
        "only_unannotated": only_unannotated,
        "pattern_set_version": settings.pattern_set_version,
        "classifier_model_path": settings.classifier_model_path,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"{settings.annotate_hwm_key_prefix}:{digest}"


def _classifier_unit_batches(units: list[TextUnit]) -> list[list[TextUnit]]:
    """Return length-homogeneous classifier microbatches.

    Hugging Face pads every tokenizer call to its longest sequence. Sorting a
    single batch is therefore a no-op; sorting and then splitting into smaller
    calls is what reduces padded-token work.
    """
    if not units:
        return []
    batch_size = settings.classifier_batch_size
    if batch_size < 1:
        raise ValueError("classifier_batch_size must be at least 1")
    ordered = sorted(units, key=lambda unit: len(unit.text))
    return [ordered[i : i + batch_size] for i in range(0, len(ordered), batch_size)]


class _PhaseTimings:
    """
    Rolling per-phase timings for the annotator loop (CHANGELOG 2026-08-23).

    Each phase (parse / per-rule / classifier / batch_total) keeps a bounded
    deque of recent samples; `maybe_log` prints the median of each phase every
    `log_every_sec` (30s). Median is used instead of mean so one slow batch
    (e.g. a single very long Jira body padding a whole classifier batch) does
    not skew the reading. The cumulative-average Progress rate hid the real
    3x slowdown (instantaneous vs average) — this is the analysis instrument
    that surfaces which annotator phase is the actual bottleneck.
    """

    def __init__(self, window: int = 50, log_every_sec: float = 30.0) -> None:
        self._samples: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self._last_log = time.monotonic()
        self._every = log_every_sec

    def record(self, phase: str, seconds: float) -> None:
        self._samples[phase].append(seconds)

    def _median(self, phase: str) -> float | None:
        s = self._samples.get(phase)
        if not s:
            return None
        ordered = sorted(s)
        n = len(ordered)
        mid = n // 2
        return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2

    def maybe_log(self, label: str) -> None:
        now = time.monotonic()
        if now - self._last_log < self._every:
            return
        self._last_log = now
        parts = []
        for phase in ("fetch", "parse", "rule", "classifier", "batch_total"):
            m = self._median(phase)
            if m is not None:
                parts.append(f"{phase}={m * 1000:.0f}ms")
        logger.info(
            "%s phase timings (med, last %d batches): %s",
            label,
            self._window(),
            ", ".join(parts),
        )

    def _window(self) -> int:
        return len(self._samples[list(self._samples.keys())[0]]) if self._samples else 0


async def run_annotator_worker(
    shards: int = 1,
    shard_index: int = 0,
    id_lo: str | None = None,
    id_hi: str | None = None,
    resume: bool = False,
    resume_from: str | None = None,
    only_unannotated: bool = False,
) -> None:
    """
    Annotate one keyset range of TextUnits and publish Signals to stream_signals.

    Resume (CHANGELOG 2026-08-23): the walk is an id-ordered prefix, so a restart
    does not need to re-annotate done work. `resume_from` (explicit boundary, from
    the frontier-recovery script) or the stored high-water mark (`resume=True`) is
    passed as the initial `start_id` to _iter_text_units; every batch's last unit
    id is persisted to Redis after it is fully published, so an interrupted run
    resumes from the last complete batch rather than the start of the range.
    Signal MERGEs are idempotent, so re-doing the single boundary unit is safe.

    `only_unannotated` (CHANGELOG 2026-08-27): incremental mode. The scope adds
    "no CLASSIFIED_AS verdict AND not oversized", so only units that have never
    been annotated are parsed. Interruption recovery needs no --resume/--resume-from
    and no HWM: rerunning the same command re-selects whatever the graph says is
    still un-annotated. It requires the classifier, because its verdict is the
    completion marker; without it every in-scope unit would be re-parsed forever
    without ever dropping out of scope.

    v0.5 speed model:
      - ONE shared spaCy pipeline parses each unit once (nlp.pipe, batched).
      - All rule annotators run on that shared Doc.
      - The classifier batches on MPS.
      - The Neo4j query applies the configured annotation scope (language,
        min tokens, roles, parent types, skip-bots, only-referenced-PRs), so
        units that are not worth annotating are never fetched or parsed.
      - Signals from a whole batch are flushed with ONE publish_many per batch
        (CHANGELOG 2026-08-20, Milestone B) instead of one XADD per signal.

    Sharding (CHANGELOG 2026-08-21, Milestone E): when shards > 1, each process
    annotates a disjoint [id_lo, id_hi) range of the ordered TextUnit id space,
    so K processes can split the corpus across CPU cores. The range is applied
    to the count query, the pagination, and Progress, so each shard reports its
    own total and ETA. id_lo/id_hi are optional; None = unbounded on that side.

    Backpressure (CHANGELOG 2026-08-21, Milestone D): after each publish, the
    worker waits if stream_signals exceeds settings.annotator_max_stream_signals_backlog
    (mirrors extractor/worker.py's stream_units ceiling). With the concurrent
    Phase-2 projector draining the stream, this keeps Redis bounded regardless
    of how many shards are producing.

    See CHANGELOG 2026-06-04 (parse-once) and 2026-08-20 (oversize skip +
    per-unit fallback).
    """
    from neo4j import AsyncGraphDatabase

    from annotators.base import make_nlp

    broker = await get_broker()
    nlp = make_nlp()
    # Strict in incremental mode (CHANGELOG 2026-08-27): abort if ANY expected
    # annotator (rule or classifier) fails to load — a unit must be fully
    # annotated before its ClassifierVerdict marks it complete.
    annotators = _load_annotators(nlp, strict=only_unannotated)

    from annotators.classifier import ClassifierAnnotator

    clf_annotators = [a for a in annotators if isinstance(a, ClassifierAnnotator)]
    rule_annotators = [a for a in annotators if not isinstance(a, ClassifierAnnotator)]

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )

    # Resume boundary: explicit --resume-from wins; otherwise the stored
    # high-water mark (if resume=True and one exists within this range).
    label = f"Annotate[{shard_index + 1}/{shards}]" if shards > 1 else "Annotate"
    start_id = id_lo
    if resume:
        hwm = await broker.get(_hwm_key(id_lo, id_hi, only_unannotated=only_unannotated))
        hwm_in_range = hwm is not None and (id_lo is None or hwm >= id_lo)
        hwm_in_range = hwm_in_range and (id_hi is None or hwm < id_hi)
        if hwm_in_range:
            start_id = hwm
            logger.info("%s resuming from high-water mark %s", label, hwm)
        elif hwm is not None:
            logger.warning("%s ignoring out-of-range high-water mark %s", label, hwm)
    if resume_from is not None:
        start_id = resume_from
        logger.info("%s resuming from explicit boundary %s", label, resume_from)
    if start_id:
        logger.info("%s starting at id %s (resumed).", label, start_id)

    where, params = _scope_filter(only_unannotated=only_unannotated)
    where, params = _shard_where(where, params, id_lo, id_hi)
    count_where = where
    count_params = dict(params)
    if start_id:
        count_where = (
            f"{count_where} AND u.id >= $start_id" if count_where else ("WHERE u.id >= $start_id")
        )
        count_params["start_id"] = start_id
    async with driver.session() as session:
        res = await session.run(
            f"MATCH (u:TextUnit) {count_where} RETURN count(u) AS n", **count_params
        )
        rec = await res.single()
        total_units = rec["n"] if rec else 0

    prog = Progress(label, total=total_units)
    logger.info("%s started. %d TextUnits in scope.", label, total_units)

    batch_size = settings.annotator_batch_size
    pending: list[TextUnit] = []
    total = 0
    skipped = 0
    timings = _PhaseTimings()
    hwm_key = _hwm_key(id_lo, id_hi, only_unannotated=only_unannotated)

    async def process_batch(units: list[TextUnit]) -> None:
        nonlocal skipped
        t0 = time.monotonic()
        n_skipped, _n_annotated, payloads, complete = await _annotate_batch(
            units, nlp, rule_annotators, clf_annotators, timings=timings
        )
        skipped += n_skipped
        if payloads:
            await broker.publish_many(settings.stream_signals, payloads)
            await _wait_for_backlog(broker)
        timings.record("batch_total", time.monotonic() - t0)
        timings.maybe_log(label)
        if not complete:
            raise RuntimeError(
                f"{label} batch ending at {units[-1].text_unit_id} was incomplete; "
                "published successful signals but did not advance the resume mark"
            )

    try:
        async for unit in _iter_text_units(
            driver, where, params, page_size=batch_size * 8, start_id=start_id
        ):
            pending.append(unit)
            if len(pending) >= batch_size:
                await process_batch(pending)
                total += len(pending)
                # Persist the resume mark only after the batch is fully published
                # (idempotent Signal MERGEs make re-doing the single boundary unit
                # safe, so the mark = the last unit of the last complete batch).
                await broker.set(hwm_key, pending[-1].text_unit_id)
                prog.add(len(pending))
                prog.maybe_log()
                pending = []
        if pending:
            await process_batch(pending)
            total += len(pending)
            await broker.set(hwm_key, pending[-1].text_unit_id)
            prog.add(len(pending))
    finally:
        await driver.close()

    prog.finish()
    logger.info(
        "%s finished. Annotated %d TextUnits (%d skipped as oversized).",
        label,
        total,
        skipped,
    )


async def _wait_for_backlog(broker: Any) -> None:
    """
    Pause the producer if stream_signals has grown past the configured ceiling.

    This is the annotator-side analogue of extractor/worker.py's stream_units
    backlog gate (settings.extractor_max_stream_units_backlog, CHANGELOG
    2026-08-16). It structurally prevents a fast set of shards from exhausting
    Redis's hard memory limit while the concurrent projector drains behind them.
    """
    ceiling = settings.annotator_max_stream_signals_backlog
    if ceiling <= 0:
        return
    while True:
        n = await broker.stream_length(settings.stream_signals)
        if n <= ceiling:
            return
        await asyncio.sleep(1.0)


async def _annotate_batch(
    units: list[TextUnit],
    nlp: Any,
    rule_annotators: list[Any],
    clf_annotators: list[Any],
    timings: _PhaseTimings | None = None,
) -> tuple[int, int, list[dict[str, Any]], bool]:
    """
    Annotate one batch of TextUnits and return the serialised Signal payloads.

    Pure compute + serialisation — all I/O (publishing) is deferred to the
    caller so this stays testable without Redis. The caller flushes the
    returned payloads with a single `publish_many` per batch.

    Fault tolerance (CHANGELOG 2026-08-20):
      - Units longer than settings.annotate_max_chars are SKIPPED before parsing.
        spaCy's parser caps input at nlp.max_length (1M default) and raises
        [E088] past that; a >100k-char unit is a pasted log/stack trace, not
        epistemic discourse, so it is skipped as a scope decision (same class
        as annotate_min_tokens — NOT signal filtering, AGENTS.md §5.3).
      - If the shared nlp.pipe pass raises partway (e.g. an unexpected failure on
        one unit), we fall back to parsing each unit individually with its own
        try/except, so one bad unit degrades to a skip instead of halting the run.
      - The per-annotator try/except (pre-existing) isolates a single annotator's
        failure from its siblings; "no annotator error can block the others".

    Classifier padding fix (CHANGELOG 2026-08-23): `parsed_units` is sorted by
    text length and split into classifier microbatches. HF tokenisation pads
    every tokenizer call to its longest sequence, so one long Jira body
    previously padded the other 63 units to 512 tokens. Sorting alone would not
    change that maximum; splitting is what reduces padded-token work.

    Returns (n_skipped_oversize, n_annotated, payloads, complete). `complete`
    is false after any unexpected parse/annotator/classifier failure; the
    worker then stops without advancing its contiguous resume mark.
    """
    max_chars = settings.annotate_max_chars
    parseable: list[TextUnit] = []
    n_skipped = 0
    for unit in units:
        if len(unit.text) > max_chars:
            logger.warning(
                "Skipping oversized TextUnit %s (parent_type=%s, %d chars > %d)",
                unit.text_unit_id,
                unit.parent_type or "?",
                len(unit.text),
                max_chars,
            )
            n_skipped += 1
            continue
        parseable.append(unit)
    if not parseable:
        return n_skipped, 0, [], True

    # Parse the whole batch in one shared pass. Materialised inside the try so a
    # lazily-raised pipe error (E088 or otherwise) is caught here.
    t_parse = time.monotonic()
    complete = True
    try:
        texts = [u.text for u in parseable]
        docs = nlp.pipe(texts, batch_size=len(texts), n_process=settings.spacy_n_process)
        pairs = list(zip(parseable, docs, strict=False))
    except Exception:
        # Fall back to per-unit parsing so one bad unit can't sink the batch.
        # This re-parses the whole batch on a mid-stream pipe failure, which is
        # acceptable: the size filter above makes hard pipe failures rare.
        logger.warning("Batch spaCy parse failed on %d units; retrying per-unit.", len(parseable))
        pairs = []
        for unit in parseable:
            try:
                pairs.append((unit, nlp(unit.text)))
            except Exception as exc:
                logger.error("Skipping TextUnit %s (parse failed): %s", unit.text_unit_id, exc)
                complete = False
    if timings is not None:
        timings.record("parse", time.monotonic() - t_parse)

    payloads: list[dict[str, Any]] = []
    n_annotated = 0
    t_rule = time.monotonic()
    for unit, doc in pairs:
        n_annotated += 1
        for ann in rule_annotators:
            try:
                for sig in ann.annotate(unit, doc):
                    payloads.append(_signal_to_payload(sig))
            except Exception as exc:
                logger.error("Annotator %s failed on %s: %s", ann.name, unit.text_unit_id, exc)
                complete = False
    if timings is not None:
        timings.record("rule", time.monotonic() - t_rule)
    # Classifier batch (MPS). Only units that actually parsed — oversized ones
    # were excluded above, and a per-unit parse failure must drop the unit from
    # the classifier too, or it would carry signals here but none from the rule
    # annotators (a partial, incoherent TextUnit).
    parsed_units = [u for u, _ in pairs]
    t_clf = time.monotonic()
    for clf in clf_annotators:
        try:
            for classifier_batch in _classifier_unit_batches(parsed_units):
                for sig in clf.batch_annotate(classifier_batch):
                    payloads.append(_signal_to_payload(sig))
        except Exception as exc:
            logger.error("ClassifierAnnotator batch failed: %s", exc)
            complete = False
    if timings is not None:
        timings.record("classifier", time.monotonic() - t_clf)

    # Completion-marker safety (CHANGELOG 2026-08-27): when a batch is
    # INCOMPLETE (a parse/rule/classifier failure), never hand the projector a
    # __verdict__ payload for any unit in it. The verdict is what incremental
    # mode uses to decide a unit is "done"; publishing one for a unit whose rule
    # signals are known to be partial would permanently drop it out of the
    # un-annotated selection on the recovery rerun. Suppressing ALL verdicts for
    # the batch means the whole batch is retried (MERGEs are idempotent), so the
    # successful non-verdict signals we do publish are simply refreshed.
    if not complete:
        payloads = [p for p in payloads if not (p.get("payload") or {}).get("__verdict__")]

    return n_skipped, n_annotated, payloads, complete


def _signal_to_payload(sig: Signal) -> dict[str, Any]:
    """Serialise a Signal to the stream_signals event shape (BUILD_SPEC §4.3)."""
    return {
        "signal_id": sig.signal_id,
        "text_unit_id": sig.text_unit_id,
        "layer": sig.layer,
        "category": sig.category,
        "subcategory": sig.subcategory,
        "surface_form": sig.surface_form,
        "span_start": sig.span_start,
        "span_end": sig.span_end,
        "rule_id": sig.rule_id,
        "rule_version": sig.rule_version,
        "confidence": sig.confidence,
        # v0.2 (MARKER_REVIEW.md §3.5) — must be forwarded here or they never
        # reach the projector; the Signal dataclass carries them but this
        # dict is a manual field list, not dataclasses.asdict().
        "weight": sig.weight,
        "status": sig.status,
        "payload": sig.payload,
    }


def _scope_filter(only_unannotated: bool = False) -> tuple[str, dict[str, Any]]:
    """
    Build the WHERE clause + params that implement the configured annotation
    scope. Returns ("WHERE ...", params) or ("", {}) if no filters are active.
    Each clause is null-safe so it does not silently drop pre-v0.5 data that
    lacks the newer node fields.

    `only_unannotated` (CHANGELOG 2026-08-27): incremental mode — restrict to
    units that have no ClassifierVerdict yet (NOT EXISTS CLASSIFIED_AS) AND are
    not oversized. Oversized units are deliberately skipped before parsing, so
    they can never carry a verdict and would otherwise reappear as perpetual
    "holes". The verdict is the completion marker, so once all plain signals +
    wiring are projected and the verdict is written last, the unit drops out of
    scope. Callers that reuse this filter for the count, pagination, and shard
    balancing automatically measure only the remaining work.
    """
    clauses: list[str] = []
    params: dict[str, Any] = {}

    if settings.annotate_languages:
        clauses.append("(u.lang IN $langs OR u.lang IS NULL)")
        params["langs"] = settings.annotate_languages
    if settings.annotate_min_tokens > 0:
        clauses.append("coalesce(u.token_count, 0) >= $min_tokens")
        params["min_tokens"] = settings.annotate_min_tokens
    if settings.annotate_roles:
        clauses.append("(u.role IN $roles OR u.role IS NULL)")
        params["roles"] = settings.annotate_roles
    if settings.annotate_parent_types:
        clauses.append("(u.parent_type IN $ptypes OR u.parent_type IS NULL)")
        params["ptypes"] = settings.annotate_parent_types
    if settings.annotate_skip_bots:
        clauses.append("(u.author_login IS NULL OR NOT u.author_login ENDS WITH '[bot]')")
    if settings.annotate_only_referenced_prs:
        # Keep non-PR units; keep PR units only if their PR has a REFERENCES edge
        # to/from an Issue. Requires the reference-enrichment pass to have run.
        clauses.append(
            "(coalesce(u.parent_type,'') <> 'pull_request' "
            "OR EXISTS { MATCH (pr:PullRequest)-[:HAS_TEXT]->(u) "
            "MATCH (pr)-[:REFERENCES]-(:Issue) })"
        )
    if only_unannotated:
        clauses.append("size(u.text) <= $max_chars")
        params["max_chars"] = settings.annotate_max_chars
        clauses.append("NOT EXISTS { MATCH (u)-[:CLASSIFIED_AS]->() }")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


async def count_in_scope(
    only_unannotated: bool = False,
    id_lo: str | None = None,
    id_hi: str | None = None,
) -> int:
    """Count TextUnits in the annotation scope (optionally within an id range).

    Used by run_pipeline.py to decide, in incremental mode, whether there is any
    work at all (zero → drain + exit) and whether to reduce the requested shard
    count below the remaining unit count (fewer units than shards would make the
    token-quantile boundary scan fail). Reads the same _scope_filter the worker
    uses, so the count matches exactly what the workers will parse.
    """
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        where, params = _scope_filter(only_unannotated=only_unannotated)
        where, params = _shard_where(where, params, id_lo, id_hi)
        async with driver.session() as session:
            res = await session.run(f"MATCH (u:TextUnit) {where} RETURN count(u) AS n", **params)
            rec = await res.single()
            return rec["n"] if rec else 0
    finally:
        await driver.close()


def _shard_where(
    where: str,
    params: dict[str, Any],
    id_lo: str | None,
    id_hi: str | None,
) -> tuple[str, dict[str, Any]]:
    """
    Append disjoint [id_lo, id_hi) range bounds to an existing scope WHERE.

    Returns (where, params). id_lo/id_hi may be None (unbounded on that side).
    The keyset pagination in _iter_text_units then walks `u.id` within the
    range, so parallel shards split the corpus with no overlap and no gaps.
    """
    if id_lo is None and id_hi is None:
        return where, params
    clauses: list[str] = []
    if id_lo is not None:
        clauses.append("u.id >= $id_lo")
        params["id_lo"] = id_lo
    if id_hi is not None:
        clauses.append("u.id < $id_hi")
        params["id_hi"] = id_hi
    joined = " AND ".join(clauses)
    where = f"{where} AND {joined}" if where else f"WHERE {joined}"
    return where, params


async def compute_shard_boundaries(
    shards: int,
    id_lo: str | None = None,
    only_unannotated: bool = False,
) -> list[str]:
    """
    Compute shards-1 TextUnit.id boundaries splitting the corpus into ranges of
    ~equal PARSE WORK, ordered lexicographically. Returns K-1 ids; the caller
    forms ranges [lo0, b1), [b1, b2), ..., [b_{K-1}, None) where lo0 is
    `id_lo` (or None for the full corpus).

    `only_unannotated` (CHANGELOG 2026-08-27): when incremental, the total and
    the scan apply the incremental scope (no CLASSIFIED_AS, not oversized), so
    boundaries balance ONLY the remaining un-annotated work — otherwise the
    ~31.5M already-annotated units would dominate the token quantiles and
    collapse all new units into one shard.

    `id_lo` (CHANGELOG 2026-08-23): when resuming from a frontier (--resume-from),
    boundaries balance the REMAINING range [id_lo, max) instead of the whole
    corpus. The token total and the keyset scan BOTH include `u.id >= $lo` (the
    half-open shard ranges the workers use are [lo, hi), so the boundary unit's
    tokens belong to the shard that starts at it).

    The total and the scan apply the SAME annotation scope filter as the worker
    count/pagination (via _scope_filter), so the boundaries partition only the
    in-scope units the annotator will actually parse. Without this, out-of-scope
    units (below min tokens, non-en, bots, referenced-PR exceptions) would skew
    the token quantiles and badly imbalance the shards.

    Boundaries balance cumulative `token_count` (a stored whitespace-token
    estimate, a good proxy for spaCy parse cost), NOT node count. Parse cost
    scales with text length, so count-quantiles are the wrong target: on the
    live corpus a K=2 count split put the short chat/issue units in shard 0 and
    the long Jira bodies in shard 1, producing 305/s vs 72/s and leaving the
    slow shard as the wall-clock bottleneck (CHANGELOG 2026-08-21, Milestone E).

    Uses ONE ordered keyset pagination pass over TextUnit.id (ORDER BY u.id is
    served by the uniqueness index) accumulating `token_count`, recording the
    id at each token-quantile. `token_count` is a stored integer, so this avoids
    the expensive `size(u.text)` full scans (which OOM'd/ran minutes). Chosen
    over two rejected alternatives after live timing against the 23.4M-unit
    corpus:
      - Per-probe `ORDER BY ... SKIP n LIMIT 1`: 44s for ONE SKIP-11M probe;
        K-1 of them scan from the start each time (~330s for K=8).
      - A single unbounded ordered stream: OOMs the server transaction memory.
    Keyset pagination scans the index once in bounded pages (~3-4 min for K=8)
    — the O(N) floor for exact quantile boundaries.
    """
    from neo4j import AsyncGraphDatabase

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        # Use the exact annotation scope so the boundary scan partitions the
        # same population the workers count/parse.
        scope_where, scope_params = _scope_filter(only_unannotated=only_unannotated)
        scope_clauses = scope_where[len("WHERE ") :] if scope_where.startswith("WHERE ") else ""

        async with driver.session() as session:
            # Total in-scope tokens at id >= id_lo (or all in-scope if id_lo is None).
            sum_pred = f"({scope_clauses})" if scope_clauses else "TRUE"
            sum_params = dict(scope_params)
            if id_lo is not None:
                sum_pred = f"{sum_pred} AND u.id >= $lo"
                sum_params["lo"] = id_lo
            total_toks = (
                await (
                    await session.run(
                        "MATCH (u:TextUnit) WHERE "
                        + sum_pred
                        + " RETURN coalesce(sum(u.token_count), 0) AS toks",
                        **sum_params,
                    )
                ).single()
            )["toks"]

            rows: list[tuple[str, int]] = []
            last_id = id_lo or ""
            page = 10_000
            first = id_lo is not None
            while True:
                # First page INCLUSIVE at id_lo (matching the half-open ranges),
                # later pages exclusive (keyset).
                pred = "u.id >= $last" if first else "u.id > $last"
                first = False
                page_rows = await _scan_tokens(
                    session, pred, scope_clauses, last_id, page, scope_params
                )
                if not page_rows:
                    break
                rows.extend(page_rows)
                last_id = page_rows[-1][0]
                # Once every quantile threshold is crossed the boundaries are
                # final; stop paging (the scan need not walk the whole corpus).
                try:
                    boundaries = _quantile_boundaries(total_toks, shards, rows)
                    return boundaries
                except RuntimeError:
                    continue
            return _quantile_boundaries(total_toks, shards, rows)
    finally:
        await driver.close()


async def _scan_tokens(
    session: Any,
    pred: str,
    scope_clauses: str,
    last_id: str,
    page: int,
    scope_params: dict[str, Any],
) -> list[tuple[str, int]]:
    """One keyset page of (id, token_count) for the boundary scan."""
    where = f"({scope_clauses}) AND {pred}" if scope_clauses else pred
    result = await session.run(
        "MATCH (u:TextUnit) WHERE "
        + where
        + " RETURN u.id AS id, coalesce(u.token_count, 0) AS toks "
        "ORDER BY u.id LIMIT $n",
        last=last_id,
        n=page,
        **scope_params,
    )
    return [(r["id"], r["toks"]) async for r in result]


def _quantile_boundaries(total_tokens: int, shards: int, rows: list[tuple[str, int]]) -> list[str]:
    """Return shards-1 ids splitting `rows` (ordered id, token_count pairs) into
    ~equal cumulative-token ranges.

    `rows` is a prefix of the ordered (id, token_count) scan; the quantile
    thresholds are computed from `total_tokens` (the whole in-scope total), and
    each threshold's boundary is the id of the first row whose cumulative count
    reaches it. Pure function so the boundary algorithm is unit-testable without
    a Neo4j driver.
    """
    want = sorted(total_tokens * i // shards for i in range(1, shards))
    found: dict[int, str] = {}
    cum = 0
    for uid, toks in rows:
        cum += toks
        # A boundary is the FIRST row whose cumulative count STRICTLY exceeds
        # the threshold. The shard ranges are [lo, hi) half-open; assigning the
        # row where cum == threshold to the PREVIOUS shard would hand a large
        # crossing unit to the wrong bucket and unbalance the split.
        for s in [t for t in want if t < cum and t not in found]:
            found[s] = uid
    missing = [s for s in want if s not in found]
    if missing:
        raise RuntimeError(
            f"Shard boundary scan crossed only {len(found)}/{len(want)} "
            f"token quantiles — TextUnit id space inconsistent with "
            f"sum(token_count)? (missing thresholds: {missing[:5]})"
        )
    return [found[s] for s in want]


def _run_annotator_shard(
    shard_index: int,
    shards: int,
    id_lo: str | None,
    id_hi: str | None,
    resume: bool = False,
    resume_from: str | None = None,
    only_unannotated: bool = False,
) -> None:
    """
    Child-process entrypoint: run one annotator shard to completion.

    Passed to multiprocessing.get_context("spawn").Process from
    scripts/run_pipeline.py. Runs an event loop here because spawn children do
    not inherit the parent's asyncio context.
    """
    import asyncio

    asyncio.run(
        run_annotator_worker(
            shards=shards,
            shard_index=shard_index,
            id_lo=id_lo,
            id_hi=id_hi,
            resume=resume,
            resume_from=resume_from,
            only_unannotated=only_unannotated,
        )
    )


async def _iter_text_units(
    driver: Any,
    where: str,
    params: dict[str, Any],
    page_size: int = 500,
    start_id: str | None = None,
):
    """
    Stream in-scope TextUnits from Neo4j using keyset pagination on `id`
    (O(log n) per page, unlike SKIP). Yields minimal TextUnit objects — only
    `text` and `text_unit_id` are used by annotators.

    `start_id`: resume boundary (CHANGELOG 2026-08-23). The FIRST page uses
    `u.id >= $start` (inclusive) so the boundary unit itself is re-annotated —
    safe, since Signal MERGEs are idempotent — then subsequent pages use
    `u.id > $last_id`. None/empty means start from the beginning.
    """
    last_id = start_id or ""
    first = start_id is not None and start_id != ""
    while True:
        if first:
            pred = "u.id >= $last_id"
        else:
            pred = "u.id > $last_id"
        first = False
        q = f"""
            MATCH (u:TextUnit)
            {where}{" AND" if where else "WHERE"} {pred}
            RETURN u.id AS id, u.text AS text, u.parent_type AS parent_type
            ORDER BY u.id
            LIMIT $limit
        """
        async with driver.session() as session:
            result = await session.run(q, last_id=last_id, limit=page_size, **params)
            rows = [(r["id"], r["text"], r["parent_type"]) async for r in result]
        if not rows:
            return
        for tu_id, text, parent_type in rows:
            yield TextUnit(
                text_unit_id=tu_id,
                parent_id="",
                parent_type=parent_type or "",
                repo="",
                parent_number=None,
                role="",
                position=0,
                text=text or "",
                lang=None,
                token_count=0,
                sha256="",
                author_login=None,
                created_at=None,
            )
        last_id = rows[-1][0]


def _event_to_text_unit(event: dict[str, Any]) -> TextUnit | None:
    """Reconstruct a TextUnit from the stream_units event dict."""
    from annotators.base import TextUnit as TU

    try:
        return TU(
            text_unit_id=event["text_unit_id"],
            parent_id=event["parent_id"],
            parent_type=event["parent_type"],
            repo=event["repo"],
            parent_number=event.get("parent_number"),
            role=event["role"],
            position=event["position"],
            text=event["text"],
            lang=event.get("lang"),
            token_count=event.get("token_count", 0),
            sha256=event.get("sha256", ""),
            author_login=event.get("author_login"),
            created_at=event.get("created_at"),
        )
    except KeyError as exc:
        logger.warning("Malformed TextUnit event, missing field %s. Skipping.", exc)
        return None
