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
import dataclasses
import logging
from typing import Any

from annotators.base import Signal, TextUnit
from broker import get_broker
from settings import settings
from progress import Progress

logger = logging.getLogger(__name__)


def _load_annotators(nlp) -> list[Any]:
    """
    Instantiate all annotators against a single shared spaCy pipeline `nlp`.
    Rule annotators build their matchers from nlp.vocab and operate on the
    pre-parsed Doc the worker supplies — the text is parsed once per unit.
    ClassifierAnnotator is excluded if no model path is configured.
    """
    annotators = []

    try:
        from annotators.lexical import LexiconAnnotator
        annotators.append(LexiconAnnotator(nlp))
    except Exception as exc:
        logger.error("Could not load LexiconAnnotator: %s", exc)

    try:
        from annotators.morpho_syntactic import SpacyMorphoAnnotator
        annotators.append(SpacyMorphoAnnotator(nlp))
    except Exception as exc:
        logger.error("Could not load SpacyMorphoAnnotator: %s", exc)

    try:
        from annotators.word_formation import AffixAnnotator
        annotators.append(AffixAnnotator(nlp))
    except Exception as exc:
        logger.error("Could not load AffixAnnotator: %s", exc)

    try:
        from annotators.rhetorical import RhetoricalAnnotator
        annotators.append(RhetoricalAnnotator(nlp))
    except Exception as exc:
        logger.error("Could not load RhetoricalAnnotator: %s", exc)

    try:
        from annotators.classifier import ClassifierAnnotator
        import os
        if os.path.isdir(settings.classifier_model_path):
            annotators.append(ClassifierAnnotator())
        else:
            logger.warning(
                "Classifier model not found at '%s'. Skipping ClassifierAnnotator.",
                settings.classifier_model_path,
            )
    except Exception as exc:
        logger.error("Could not load ClassifierAnnotator: %s", exc)

    logger.info("Annotator worker: %d annotators loaded.", len(annotators))
    return annotators


async def run_annotator_worker() -> None:
    """
    Annotate TextUnits read from Neo4j and publish Signals to stream_signals.

    v0.5 speed model:
      - ONE shared spaCy pipeline parses each unit once (nlp.pipe, batched).
      - All rule annotators run on that shared Doc.
      - The classifier batches on MPS.
      - The Neo4j query applies the configured annotation scope (language,
        min tokens, roles, parent types, skip-bots, only-referenced-PRs), so
        units that are not worth annotating are never fetched or parsed.
    See CHANGELOG 2026-06-04.
    """
    from neo4j import AsyncGraphDatabase

    from annotators.base import make_nlp

    broker = await get_broker()
    nlp = make_nlp()
    annotators = _load_annotators(nlp)

    from annotators.classifier import ClassifierAnnotator
    clf_annotators = [a for a in annotators if isinstance(a, ClassifierAnnotator)]
    rule_annotators = [a for a in annotators if not isinstance(a, ClassifierAnnotator)]

    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )

    where, params = _scope_filter()
    async with driver.session() as session:
        res = await session.run(f"MATCH (u:TextUnit) {where} RETURN count(u) AS n", **params)
        rec = await res.single()
        total_units = rec["n"] if rec else 0
    prog = Progress("Annotate", total=total_units)
    logger.info("Annotator worker started. %d TextUnits in scope.", total_units)

    batch_size = settings.annotator_batch_size
    pending: list[TextUnit] = []
    total = 0

    async def process_batch(units: list[TextUnit]) -> None:
        if not units:
            return
        texts = [u.text for u in units]
        # Parse the whole batch in one shared pass.
        docs = nlp.pipe(texts, batch_size=len(texts), n_process=settings.spacy_n_process)
        for unit, doc in zip(units, docs):
            for ann in rule_annotators:
                try:
                    for sig in ann.annotate(unit, doc):
                        await _publish_signal(broker, sig)
                except Exception as exc:
                    logger.error("Annotator %s failed on %s: %s", ann.name, unit.text_unit_id, exc)
        # Classifier batch (MPS)
        for clf in clf_annotators:
            try:
                for sig in clf.batch_annotate(units):
                    await _publish_signal(broker, sig)
            except Exception as exc:
                logger.error("ClassifierAnnotator batch failed: %s", exc)

    try:
        async for unit in _iter_text_units(driver, where, params, page_size=batch_size * 8):
            pending.append(unit)
            if len(pending) >= batch_size:
                await process_batch(pending)
                total += len(pending)
                prog.add(len(pending)); prog.maybe_log()
                pending = []
        if pending:
            await process_batch(pending)
            total += len(pending)
            prog.add(len(pending))
    finally:
        await driver.close()

    prog.finish()
    logger.info("Annotator worker finished. Annotated %d TextUnits.", total)


def _scope_filter() -> tuple[str, dict[str, Any]]:
    """
    Build the WHERE clause + params that implement the configured annotation
    scope. Returns ("WHERE ...", params) or ("", {}) if no filters are active.
    Each clause is null-safe so it does not silently drop pre-v0.5 data that
    lacks the newer node fields.
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

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


async def _iter_text_units(driver: Any, where: str, params: dict[str, Any], page_size: int = 500):
    """
    Stream in-scope TextUnits from Neo4j using keyset pagination on `id`
    (O(log n) per page, unlike SKIP). Yields minimal TextUnit objects — only
    `text` and `text_unit_id` are used by annotators.
    """
    last_id = ""
    while True:
        q = f"""
            MATCH (u:TextUnit)
            {where}{' AND' if where else 'WHERE'} u.id > $last_id
            RETURN u.id AS id, u.text AS text
            ORDER BY u.id
            LIMIT $limit
        """
        async with driver.session() as session:
            result = await session.run(q, last_id=last_id, limit=page_size, **params)
            rows = [(r["id"], r["text"]) async for r in result]
        if not rows:
            return
        for tu_id, text in rows:
            yield TextUnit(
                text_unit_id=tu_id, parent_id="", parent_type="", repo="",
                parent_number=None, role="", position=0, text=text or "",
                lang=None, token_count=0, sha256="", author_login=None, created_at=None,
            )
        last_id = rows[-1][0]




async def _publish_signal(broker: Any, sig: Signal) -> None:
    """Serialise a Signal and publish it to stream_signals."""
    payload = {
        "signal_id":     sig.signal_id,
        "text_unit_id":  sig.text_unit_id,
        "layer":         sig.layer,
        "category":      sig.category,
        "subcategory":   sig.subcategory,
        "surface_form":  sig.surface_form,
        "span_start":    sig.span_start,
        "span_end":      sig.span_end,
        "rule_id":       sig.rule_id,
        "rule_version":  sig.rule_version,
        "confidence":    sig.confidence,
        # v0.2 (MARKER_REVIEW.md §3.5) — must be forwarded here or they never
        # reach the projector; the Signal dataclass carries them but this
        # dict is a manual field list, not dataclasses.asdict().
        "weight":        sig.weight,
        "status":        sig.status,
        "payload":       sig.payload,
    }
    await broker.publish(settings.stream_signals, payload)


def _event_to_text_unit(event: dict[str, Any]) -> TextUnit | None:
    """Reconstruct a TextUnit from the stream_units event dict."""
    from annotators.base import TextUnit as TU
    try:
        return TU(
            text_unit_id  = event["text_unit_id"],
            parent_id     = event["parent_id"],
            parent_type   = event["parent_type"],
            repo          = event["repo"],
            parent_number = event.get("parent_number"),
            role          = event["role"],
            position      = event["position"],
            text          = event["text"],
            lang          = event.get("lang"),
            token_count   = event.get("token_count", 0),
            sha256        = event.get("sha256", ""),
            author_login  = event.get("author_login"),
            created_at    = event.get("created_at"),
        )
    except KeyError as exc:
        logger.warning("Malformed TextUnit event, missing field %s. Skipping.", exc)
        return None
