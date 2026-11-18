#!/usr/bin/env python3
"""
scripts/corpus_census.py

Shared corpus-census helpers for the v0.3 curated MSR scope
(FRAMEWORK_DESIGN.md §12). Both `scripts/run_pipeline.py` (pre-flight check and
`--census` dashboard) and `scripts/republish_events.py` (audit summary) use
these to answer the same question: *what exactly is already in MongoDB, and is
anything from the canonical dataset list missing?*

The census is read-only: it only ever runs aggregation queries. It never writes
to Mongo, Redis, or Neo4j.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# v0.3 scope: only docs the curated ingesters wrote carry one of these corpus
# ids. Old-scope GitHub/Gmane docs (async_miner, gmane_ingester) carry NO
# corpus_id and are excluded from the census and from republishing (CHANGELOG
# 2026-08-16). Retired 2026-08-31 (CHANGELOG): `bugsrepo` (links-only, no bug
# text — would require manual reconstruction diverging from the peer-reviewed
# source) and `so-emotion-gold` (too small; data inconsistencies). Their
# ingesters remain but are out of study scope; see FRAMEWORK_DESIGN.md §12.
CURATED_CORPORA: frozenset[str] = frozenset(
    {
        "apache-jira",
        "alternative-jira",
        "numfocus",
        "curated-email-code-reviews",
        "kummerfeld-irc",
        "preethac-slack",
        "disco",
        "gittercom",
        "livechat-gitter",
        "sotorrent",
        "openment",
    }
)

# Canonical corpus_id → communicative genre (REFINED_RQS_v0.3.md §2). The four
# genres the v0.3 study reports per-genre claims over are tracker, review_email,
# chat, qa. OpenMent is a role-labelled GitHub-shaped dataset (issues/PRs), so it
# is grouped with tracker rather than standing as its own genre — a decision
# recorded 2026-10-03 (CHANGELOG), to support a later OpenMent-vs-other-tracker
# comparison. This is the single source of truth; the notebooks' registries are
# currently stale (they still emit `email`/`mentor_mentee`). See the
# TODO(design-review) note in scripts/sample_units_by_genre.py.
GENRE_BY_CORPUS: dict[str, str] = {
    "apache-jira": "tracker",
    "alternative-jira": "tracker",
    "numfocus": "tracker",
    "openment": "tracker",
    "curated-email-code-reviews": "review_email",
    "kummerfeld-irc": "chat",
    "preethac-slack": "chat",
    "disco": "chat",
    "gittercom": "chat",
    "livechat-gitter": "chat",
    "sotorrent": "qa",
}

# Study genre order (REFINED_RQS_v0.3.md §2); sampling and reporting use this.
GENRES: tuple[str, ...] = ("tracker", "review_email", "chat", "qa")


def genre_of(corpus_id: str) -> str:
    """Genre for a curated corpus_id; 'EXCLUDED' for anything out of v0.3 scope."""
    return GENRE_BY_CORPUS.get(corpus_id, "EXCLUDED")


def corpora_by_genre() -> dict[str, list[str]]:
    """Invert :data:`GENRE_BY_CORPUS` into genre → sorted corpus ids."""
    out: dict[str, list[str]] = {g: [] for g in GENRES}
    for corpus_id, genre in GENRE_BY_CORPUS.items():
        out.setdefault(genre, []).append(corpus_id)
    for genre in out:
        out[genre].sort()
    return out


# Canonical dataset list, in the order used by FRAMEWORK_DESIGN.md §12. Every
# corpus_id in CURATED_CORPORA has exactly one entry here.
CANONICAL: list[tuple[str, str]] = [
    ("apache-jira", "Apache Jira (MSR'23)"),
    ("alternative-jira", "Alternative Jira (MSR'22)"),
    ("numfocus", "NumFOCUS activity"),
    ("curated-email-code-reviews", "Curated email code reviews"),
    ("kummerfeld-irc", "Kummerfeld Ubuntu IRC"),
    ("preethac-slack", "preethac Slack (disentangled)"),
    ("disco", "DISCO-A Discord"),
    ("gittercom", "GitterCom"),
    ("livechat-gitter", "LiveChatGitter"),
    ("sotorrent", "SOTorrent"),
    ("openment", "OpenMent GSoC"),
]

# Mongo collections the curated ingesters write to.
COLLECTIONS: tuple[str, ...] = (
    "raw_external",
    "raw_emails",
    "raw_issues",
    "raw_pull_requests",
    "raw_commits",
    "raw_repositories",
)


async def mongo_corpus_counts(db: Any) -> dict[str, int]:
    """
    Count curated documents per corpus_id across all raw collections.

    Returns {corpus_id: count}. A doc counts when `corpus_id` or
    `_meta.corpus_id` is in CURATED_CORPORA; everything else (old GitHub/Gmane)
    is ignored. One aggregation per present collection (single scan each), so
    on the full 15M-doc email collection this takes a few tens of seconds.
    """
    names: set[str] = set(await db.list_collection_names())
    curated_sorted = sorted(CURATED_CORPORA)
    counts: dict[str, int] = {}
    for coll_name in COLLECTIONS:
        if coll_name not in names:
            continue
        coll = db[coll_name]
        pipe = [
            {
                "$match": {
                    "$or": [
                        {"corpus_id": {"$in": curated_sorted}},
                        {"_meta.corpus_id": {"$in": curated_sorted}},
                    ]
                }
            },
            {"$project": {"corpus": {"$ifNull": ["$corpus_id", "$_meta.corpus_id"]}}},
            {"$group": {"_id": "$corpus", "count": {"$sum": 1}}},
        ]
        try:
            async for r in coll.aggregate(pipe):
                counts[r["_id"]] = counts.get(r["_id"], 0) + r["count"]
        except Exception as exc:  # a read-only diagnostic must not kill the run
            logger.warning("Census scan of %s failed: %s", coll_name, exc)
    return counts


def pending_corpora(counts: dict[str, int]) -> list[tuple[str, str]]:
    """(corpus_id, label) pairs with zero documents in MongoDB."""
    return [(cid, label) for cid, label in CANONICAL if counts.get(cid, 0) == 0]


def format_census(counts: dict[str, int], indent: str = "  ") -> list[str]:
    """Human-readable lines, one per canonical dataset, with ingest status."""
    lines: list[str] = []
    for cid, label in CANONICAL:
        n = counts.get(cid, 0)
        status = "INGESTED" if n else "PENDING"
        lines.append(f"{indent}• {label} ({cid}): {n:,} docs  [{status}]")
    return lines
