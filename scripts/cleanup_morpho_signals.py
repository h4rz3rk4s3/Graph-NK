#!/usr/bin/env python3
"""
scripts/cleanup_morpho_signals.py

OPTIONAL / MANUAL ONLY — NOT THE CHOSEN PATH (2026-10-03).
───────────────────────────────────────────────────────────
The project handles the pre-fix ``morph.syn.embedded_question`` false positives
by **filtering them at analysis time** (see ``scripts/openment_roles.py``,
``scripts/export_threads_docx.py``, ``notebooks/02*``, ``notebooks/03``), not by
purging the graph. Deleting ~21.5M nodes on the external-drive-backed store is
slow and destructive, so this script is kept only as a manual escape hatch.
Do not run it unless you have deliberately decided to remove the nodes.

One-off, batched purge of stale morpho-syntactic :Signal nodes whose rule
definition changed, so the graph stops carrying known false positives.

Background — why this exists (CHANGELOG 2026-10-03)
────────────────────────────────────────────────────
* ``morph.syn.embedded_question`` was a Matcher whose *head* token carried
  ``OP: "?"`` (optional). It therefore matched every bare
  ``if / how / when / which / what / where / why / whether`` in the corpus:
  ~21.6M signals, ~99.7% single-token false positives. The rule is now a
  scoped ``DependencyMatcher`` (wonder + wh/if clause; copula + unclear/unsure +
  wh/if clause). The stale single-token nodes must be removed.
* ``morph.mod.underspecified_cancould`` was demoted ``active -> candidate``.
  That requires **no graph write**: candidate signals are retained by design
  (signals are never filtered at ingest — AGENTS.md §5.3) and analysis already
  excludes non-active rule ids. It is listed here only so the scope is explicit;
  it is **off by default**.

What this script does / does NOT do
───────────────────────────────────
* Deletes ``:Signal`` nodes only. It never touches ``:TextUnit`` or any other
  label. ``DETACH DELETE`` also removes the ``:HAS_SIGNAL`` edge (and, for
  morpho signals, no marker/figure edges exist).
* It does **not** re-create the new rule's output. The annotator walk is
  "only unannotated", so already-annotated units will not be re-parsed by a
  normal resume. To get the new ``embedded_question`` detections for existing
  units you need a deliberate re-annotation pass (see scripts/run_pipeline.py
  --stage 2). This cleanup is the "remove the garbage" half only.

Safety / performance
────────────────────
* Dry-run is the default: it counts and prints, and deletes nothing. Pass
  ``--execute`` to actually delete.
* Deletes are issued in separate batched transactions (``LIMIT $batch``), so a
  crash loses at most one batch and the run is resumable by re-invoking.
* Counting/deleting filters on ``s.category`` first so the existing
  ``signal_cat`` index is used (there is no index on ``rule_id``).

Usage
─────
    # dry-run (default): count + print, delete nothing
    python scripts/cleanup_morpho_signals.py

    # delete the embedded_question false positives, batched, with live ETA
    python scripts/cleanup_morpho_signals.py --execute

    # scope explicitly (comma-separated; "all" = every registered target)
    python scripts/cleanup_morpho_signals.py --rules morph.syn.embedded_question --execute
    python scripts/cleanup_morpho_signals.py --rules all --execute

    # capture the run to a log while you watch it
    python scripts/cleanup_morpho_signals.py --execute 2>&1 | tee cleanup.log

DO NOT run this as an agent command (AGENTS.md §5.11): ~21M deletes take tens
of minutes. Run it yourself and watch the live ETA lines.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from progress import Progress  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("cleanup_morpho")


@dataclass(frozen=True)
class Target:
    """A registered cleanup: which rule, how to identify its stale signals."""

    rule_id: str
    category: str  # used as an index hint (signal_cat index)
    where: str  # extra Cypher predicate on the bound alias s
    default: bool  # included when --rules is not given
    reason: str


TARGETS: tuple[Target, ...] = (
    Target(
        rule_id="morph.syn.embedded_question",
        category="syntactic_pattern",
        # The new rule emits only multi-token spans (head + wh word, or copula
        # + adjective + wh word). Every single-token node is a stale false
        # positive; multi-token nodes ("wonder if", "unclear how") are genuine
        # and are kept.
        where="NOT s.surface_form CONTAINS ' '",
        default=True,
        reason="bare if/how/when/which/what/where/why/whether from the OP:'?' bug",
    ),
    Target(
        rule_id="morph.mod.underspecified_cancould",
        category="modality",
        where="true",
        default=False,
        reason=(
            "bare can/could/would — deletion only if you deliberately want to "
            "drop candidate signals; otherwise LEAVE them (analysis filters "
            "non-active rule ids automatically)"
        ),
    ),
)


def _driver():
    from neo4j import GraphDatabase

    from settings import settings

    auth = (
        None
        if settings.neo4j_password in ("none", "")
        else (settings.neo4j_user, settings.neo4j_password)
    )
    return GraphDatabase.driver(settings.neo4j_uri, auth=auth)


def _resolve_rules(raw: str) -> list[Target]:
    known = {t.rule_id: t for t in TARGETS}
    requested = [r.strip() for r in raw.split(",") if r.strip()]
    if requested == ["all"]:
        return list(TARGETS)
    unknown = [r for r in requested if r not in known]
    if unknown:
        raise SystemExit(
            f"Unknown rule(s): {', '.join(unknown)}\nKnown: {', '.join(known)} (or 'all')"
        )
    return [known[r] for r in requested]


def _count(session, target: Target) -> int:
    cypher = (
        "MATCH (s:Signal {category: $cat}) "
        f"WHERE s.rule_id = $rid AND ({target.where}) "
        "RETURN count(*) AS n"
    )
    return session.run(cypher, cat=target.category, rid=target.rule_id).single()["n"]


def _purge(
    session, target: Target, total: int, batch: int, limit: int | None, log_every: float
) -> int:
    """Batched DETACH DELETE; returns the number of nodes actually deleted."""
    effective_total = min(total, limit) if limit is not None else total
    progress = Progress(f"{target.rule_id}", total=effective_total, log_every_sec=log_every)
    cypher = (
        "MATCH (s:Signal {category: $cat}) "
        f"WHERE s.rule_id = $rid AND ({target.where}) "
        "WITH s LIMIT $batch "
        "DETACH DELETE s"
    )
    deleted = 0
    while True:
        if limit is not None and deleted >= limit:
            logger.info("%s — --limit %d reached, stopping", target.rule_id, limit)
            break
        this_batch = batch if limit is None else min(batch, limit - deleted)
        summary = session.run(
            cypher, cat=target.category, rid=target.rule_id, batch=this_batch
        ).consume()
        n = summary.counters.nodes_deleted
        if n == 0:
            break  # no candidates left
        deleted += n
        progress.add(n)
        progress.maybe_log()
    progress.finish()
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--rules",
        default=",".join(t.rule_id for t in TARGETS if t.default),
        help="Comma-separated rule ids to purge, or 'all'. "
        "Default: the rules whose definition changed and whose stale nodes are garbage.",
    )
    parser.add_argument(
        "--batch-size", type=int, default=5000, help="Deletes per transaction (default 5000)."
    )
    parser.add_argument(
        "--log-every", type=float, default=10.0, help="Seconds between progress lines (default 10)."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on nodes deleted (for a bounded trial).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete. Without this flag the script only counts (dry-run).",
    )
    args = parser.parse_args()

    logger.warning(
        "OPTIONAL TOOL — the chosen path is analysis-time filtering (2026-10-03); "
        "this purge is only for a deliberate, manual graph cleanup."
    )
    targets = _resolve_rules(args.rules)
    # Route the shared Progress logger's output through this module's logger config.
    logging.getLogger("progress").setLevel(logging.INFO)

    driver = _driver()
    try:
        with driver.session() as session:
            logger.info("Neo4j connected; counting candidates (dry scan, uses signal_cat index)…")
            counts = {}
            for t in targets:
                n = _count(session, t)
                counts[t.rule_id] = n
                logger.info("  %-40s %12s  — %s", t.rule_id, f"{n:,}", t.reason)

            grand_total = sum(counts.values())
            logger.info("Total candidate signals: %d", grand_total)

            if not args.execute:
                logger.info("DRY-RUN — nothing deleted. Re-run with --execute to purge.")
                logger.info(
                    "Expected runtime once executing: roughly ~1–2 h for ~20M nodes "
                    "(live ETA is printed after the first %ds window).",
                    int(args.log_every),
                )
                return

            logger.info(
                "EXECUTING batched DETACH DELETE (batch=%d). This is destructive; "
                "watch the live ETA below.",
                args.batch_size,
            )
            start = time.monotonic()
            total_deleted = 0
            for t in targets:
                if counts[t.rule_id] == 0:
                    logger.info("%s — 0 candidates, skipping", t.rule_id)
                    continue
                logger.info("── purging %s (%d candidates) ──", t.rule_id, counts[t.rule_id])
                total_deleted += _purge(
                    session, t, counts[t.rule_id], args.batch_size, args.limit, args.log_every
                )
            elapsed = time.monotonic() - start
            rate = total_deleted / elapsed if elapsed > 0 else 0.0
            logger.info("DONE: deleted %d signals in %.0fs (%.0f/s)", total_deleted, elapsed, rate)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
