#!/usr/bin/env python3
"""
scripts/backfill_morpho_gap.py

Targeted, spaCy-only backfill of the v0.2.2 morpho-syntactic signals that were
*added* to an existing rule but never materialised, because the annotator walk
is "only unannotated" (see CHANGELOG 2026-10-07).

Why this exists
───────────────
The 2026-10-07 cross-layer ownership pass demoted several lexical rules
(``lex.not_sure``, ``lex.not_clear_to_me``, ``lex.guess_v`` …) to *candidate*
and handed their NK reading to the morpho-syntactic layer, where scope is
enforced. Most of those morpho rules already existed and simply de-duplicate the
lexical layer (no graph write needed — the analysis resolves active/candidate
live from the YAMLs). But two rules gained **new grammatical realisations** that
are therefore absent from the graph for already-annotated units:

  * ``morph.neg.scoped_epistemic`` — copular ``be + not + sure/clear``
    ("I'm not sure", "it's not clear to me"). This is the bulk of the demoted
    ``lex.not_sure`` / ``lex.not_clear_to_me`` coverage: the old pattern only
    caught "not" as a direct child of the adjective, but spaCy attaches the
    negator to the COPULA, so the copular form was never detected.
  * ``morph.hedge.shield_think`` — the pro-form ("I guess so") and
    ``suspect + NP`` ("I suspect a race condition") realisations.
  * ``morph.epi.neg_cognition_ascribed`` — new candidate rule (negated
    know/understand with a non-1st-person subject).

Live filtering can only *exclude*, so it cannot close these gaps. This script
re-parses exactly the units at risk (those carrying the demoted lexical rules)
and writes only the target morpho signals.

Why not ``run_pipeline.py --stage 2 --only-unannotated``
────────────────────────────────────────────────────────
``--only-unannotated`` uses ``ClassifierVerdict`` as its completion marker, so
forcing it would delete every verdict and re-run the RoBERTa classifier over the
whole target set (tens of minutes, Redis backpressure) just to recover a few
spaCy matches. This script runs **only** spaCy + ``SpacyMorphoAnnotator``,
touches no verdict, no ClassifierVerdict, and no Redis, and MERGEs the new
Signals directly into Neo4j. It is idempotent (``signal_id`` =
``text_unit_id::rule_id::span_start``) and resumable (``--resume-from``).

Safety / performance
────────────────────
* Dry-run is the default: it counts the target units and writes/deletes nothing.
  Pass ``--execute`` to annotate and write.
* Reads are streamed by ``ORDER BY u.id`` and the write buffer is flushed in
  bounded transactions, so a crash loses at most one batch and the run is
  resumable with ``--resume-from <last printed id>``.
* The scope query uses the ``signal_cat`` index on ``s.category`` (there is no
  ``rule_id`` index) and ``EXISTS { … }`` so a unit is returned at most once.

Usage
─────
    # dry-run (default): count + print, write nothing
    python scripts/backfill_morpho_gap.py

    # execute, default target rules, with live progress
    python scripts/backfill_morpho_gap.py --execute 2>&1 | tee backfill.log

    # bounded trial
    python scripts/backfill_morpho_gap.py --execute --limit 5000

    # resume after an interruption (reuse the last printed unit id)
    python scripts/backfill_morpho_gap.py --execute --resume-from "issue:python/cpython:..."

DO NOT run this as an agent command (AGENTS.md §5.11): annotating ~350k units is
a user-run operation. The agent runs only the bounded dry-run count.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from progress import Progress  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("backfill_morpho_gap")

# Lexical rules whose NK reading moved to the morpho layer in v0.2.2 AND whose
# morpho replacement is genuinely missing from the graph. Deliberately narrow:
#   * lex.not_sure / lex.not_clear_to_me → morph.neg.scoped_epistemic, whose new
#     copular realisation was never materialised (the real gap).
#   * lex.dont_know / lex.cant_tell / lex.no_idea / lex.no_clue are NOT listed:
#     the pre-existing morpho patterns (neg_cognition, neg_cognition_modal,
#     scoped_epistemic realisation 1) already fired on those, so the demotion is
#     pure de-duplication — re-annotating their units adds nothing.
#   * lex.guess_v / suppose_v / assume_v / suspect_v / reckon_v are NOT listed:
#     morph.hedge.shield_think realisation (1) was already active and in the
#     graph; the demoted lexical matches were the *unscoped* ones (bare "guess",
#     non-1st-person "assume responsibility") that were intentionally demoted.
#     Only the pro-form / NP realisations can be new, and they are captured
#     incidentally on any source unit here (the target filter is rule-based).
# Override with --src-rules if a wider pass is ever wanted.
DEFAULT_SRC_RULES: tuple[str, ...] = (
    "lex.not_sure",
    "lex.not_clear_to_me",
)

# Morpho rules whose *matching changed* (new realisations). Only these are
# written back; existing signals for other rules are left untouched.
DEFAULT_TARGET_RULES: tuple[str, ...] = (
    "morph.neg.scoped_epistemic",
    "morph.hedge.shield_think",
    "morph.epi.neg_cognition_ascribed",
)

_WRITE = """
UNWIND $signals AS s
MATCH (u:TextUnit {id: s.text_unit_id})
MERGE (sig:Signal {id: s.signal_id})
  ON CREATE SET sig.layer        = s.layer,
                sig.category     = s.category,
                sig.subcategory  = s.subcategory,
                sig.surface_form = s.surface_form,
                sig.span_start   = s.span_start,
                sig.span_end     = s.span_end,
                sig.rule_id      = s.rule_id,
                sig.rule_version = s.rule_version,
                sig.confidence   = s.confidence,
                sig.weight       = s.weight,
                sig.status       = s.status,
                sig.payload_json = s.payload_json,
                sig.created_at   = datetime()
  ON MATCH  SET sig.weight       = s.weight,
                sig.status       = s.status
MERGE (u)-[:HAS_SIGNAL]->(sig)
"""


def _driver():
    from neo4j import GraphDatabase

    from settings import settings

    auth = (
        None
        if settings.neo4j_password in ("none", "")
        else (settings.neo4j_user, settings.neo4j_password)
    )
    return GraphDatabase.driver(settings.neo4j_uri, auth=auth)


def _count_targets(session, src_rules: list[str]) -> int:
    cypher = (
        "MATCH (u:TextUnit) "
        "WHERE EXISTS { MATCH (u)-[:HAS_SIGNAL]->(s:Signal {category: 'prototype'}) "
        "               WHERE s.rule_id IN $src_rules } "
        "RETURN count(u) AS n"
    )
    return session.run(cypher, src_rules=src_rules).single()["n"]


def _iter_target_units(session, src_rules: list[str], resume_from: str | None, limit: int | None):
    """Yield (id, text) for target units, ordered by id and streamed."""
    params: dict = {"src_rules": src_rules}
    guard = ""
    if resume_from:
        guard = "u.id >= $resume_from AND "
        params["resume_from"] = resume_from
    cypher = (
        "MATCH (u:TextUnit) "
        f"WHERE {guard}EXISTS {{ MATCH (u)-[:HAS_SIGNAL]->(s:Signal {{category: 'prototype'}}) "
        "               WHERE s.rule_id IN $src_rules } "
        "RETURN u.id AS id, u.text AS text ORDER BY u.id"
    )
    if limit is not None:
        cypher += " LIMIT $limit"
        params["limit"] = limit
    for rec in session.run(cypher, **params):
        yield rec["id"], rec["text"]


def _to_payload(sig) -> dict:
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
        "weight": sig.weight,
        "status": sig.status,
        "payload_json": json.dumps(
            {k: v for k, v in (sig.payload or {}).items() if not k.startswith("__")},
            default=str,
        ),
    }


def _unit(text_unit_id: str, text: str):
    """Build the minimal TextUnit the morpho annotator needs (it reads .text)."""
    from annotators.base import TextUnit

    return TextUnit(
        text_unit_id=text_unit_id,
        parent_id="",
        parent_type="",
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


def _process_chunk(session, nlp, annotator, chunk, target_rules, pending, batch_size):
    """Parse one chunk, buffer target-rule signals, flush bounded writes.

    Returns (emitted_here, last_id).
    """
    texts = [t or "" for _, t in chunk]
    ids = [uid for uid, _ in chunk]
    emitted = 0
    for uid, text, doc in zip(ids, texts, nlp.pipe(texts), strict=False):
        for sig in annotator.annotate(_unit(uid, text), doc):
            if sig.rule_id in target_rules:
                pending.append(_to_payload(sig))
                emitted += 1
        if len(pending) >= batch_size:
            session.run(_WRITE, signals=pending)
            pending.clear()
    return emitted, (ids[-1] if ids else None)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--src-rules",
        default=",".join(DEFAULT_SRC_RULES),
        help="Comma-separated lexical rule ids whose units are re-annotated.",
    )
    parser.add_argument(
        "--target-rules",
        default=",".join(DEFAULT_TARGET_RULES),
        help="Comma-separated morpho rule ids whose new matches are written back.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Cap units processed.")
    parser.add_argument(
        "--resume-from", type=str, default=None, help="Only process units with id >= this value."
    )
    parser.add_argument("--batch-size", type=int, default=5000, help="Signals per write txn.")
    parser.add_argument("--nlp-batch", type=int, default=256, help="spaCy pipe batch size.")
    parser.add_argument("--log-every", type=float, default=10.0, help="Progress interval (s).")
    parser.add_argument(
        "--execute", action="store_true", help="Annotate and write. Without it: dry-run count only."
    )
    args = parser.parse_args()

    src_rules = [r.strip() for r in args.src_rules.split(",") if r.strip()]
    target_rules = {r.strip() for r in args.target_rules.split(",") if r.strip()}
    if not src_rules or not target_rules:
        raise SystemExit("--src-rules and --target-rules must be non-empty.")

    driver = _driver()
    try:
        with driver.session() as session:
            logger.info(
                "source rules: %d; target morpho rules: %d",
                len(src_rules),
                len(target_rules),
            )
            n = _count_targets(session, src_rules)
            logger.info("candidate units: %s", f"{n:,}")

            if not args.execute:
                logger.info("DRY-RUN — nothing written. Re-run with --execute to backfill.")
                return

            from annotators.base import make_nlp
            from annotators.morpho_syntactic import SpacyMorphoAnnotator

            nlp = make_nlp()
            annotator = SpacyMorphoAnnotator(nlp)
            logger.info(
                "SpacyMorphoAnnotator v%s loaded; targets: %s",
                annotator.version,
                ", ".join(sorted(target_rules)),
            )

            progress = Progress("backfill", total=args.limit or n, log_every_sec=args.log_every)
            start = time.monotonic()
            pending: list = []
            processed = 0
            emitted = 0
            last_id: str | None = None

            chunk: list[tuple[str, str]] = []
            for uid, text in _iter_target_units(session, src_rules, args.resume_from, args.limit):
                chunk.append((uid, text))
                if len(chunk) >= args.nlp_batch:
                    emitted_here, last_id = _process_chunk(
                        session, nlp, annotator, chunk, target_rules, pending, args.batch_size
                    )
                    processed += len(chunk)
                    emitted += emitted_here
                    progress.add(len(chunk))
                    progress.maybe_log()
                    chunk = []
            if chunk:
                emitted_here, last_id = _process_chunk(
                    session, nlp, annotator, chunk, target_rules, pending, args.batch_size
                )
                processed += len(chunk)
                emitted += emitted_here
                progress.add(len(chunk))
            if pending:
                session.run(_WRITE, signals=pending)
                pending.clear()
            progress.finish()

            elapsed = time.monotonic() - start
            logger.info(
                "DONE: processed %d unit(s); emitted %d target signal(s) in %.0fs",
                processed,
                emitted,
                elapsed,
            )
            if last_id is not None:
                logger.info("resume with: --resume-from %r", last_id)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
