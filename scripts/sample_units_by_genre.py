#!/usr/bin/env python3
"""
scripts/sample_units_by_genre.py — genre-stratified random NK-unit sample.

Draws 25 TextUnits **per communicative genre** (tracker / review_email / chat /
qa) that carry at least one active non-knowledge marker, and writes them to a
CSV (and a formatted .xlsx) with unit metadata, the unit text, the *raw source
document* the unit was extracted from (fetched from MongoDB), the total marker
count, and per-layer marker counts. See REFINED_RQS_v0.3.md §2 for the genre
registry and FRAMEWORK_DESIGN.md §4 for the signal model.

Design contracts
----------------
* Read-only. Nothing here writes to Neo4j or Mongo.
* The qualifying-marker predicate and the active rule set are imported verbatim
  from ``scripts/openment_roles.py`` (the canonical analysis predicate), not
  re-derived, so sampling cannot drift from the notebook/analysis definition.
* The genre registry lives in ``scripts/corpus_census.py`` (``GENRE_BY_CORPUS``);
  OpenMent is grouped with ``tracker`` (decision 2026-10-03).
* Uniform random within a genre, reproducible given ``--seed``. Naive
  ``ORDER BY u.id LIMIT n`` is *not* used: TextUnit ids are corpus-prefixed, so
  that would select one corpus per genre. Instead a seed-derived prefix over the
  indexed, uniformly-distributed ``TextUnit.sha256`` selects an index-backed
  random subset (``ontology.cypher`` index ``textunit_sha``).

TODO(design-review): ``notebooks/03_rq_analysis.ipynb`` (and 02b) define their
own genre registries that still emit ``email``/``mentor_mentee``; they are stale
relative to GENRE_BY_CORPUS. Design docs get reconciled in a dedicated pass.

Usage
-----
    python scripts/sample_units_by_genre.py --dry-run   # counts + pool sizes only
    python scripts/sample_units_by_genre.py             # writes CSV + XLSX

The candidate-count scan touches the full signal graph; per AGENTS.md §5.11 the
user runs it (expected a few minutes on the external-drive store), bounded
read-only checks are what the agent runs afterwards.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("scripts.sample_units_by_genre")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.corpus_census import GENRES, corpora_by_genre, genre_of  # noqa: E402
from scripts.openment_roles import (  # noqa: E402
    NK_SIGNAL_PREDICATE,
    load_rule_sets,
    run_query,
)

SEED = 20261003
TARGET_PER_GENRE = 25
# Expected candidates drawn per genre; the prefix length is chosen so the
# index-backed pool is ~this size (see _choose_prefix_length).
POOL_PER_GENRE = 1000
# Transfer cap per genre; generous headroom over POOL so a duplicate-sha256-heavy
# bucket is not silently truncated.
POOL_LIMIT_MULT = 4
DEFAULT_OUT = PROJECT_ROOT / "notebooks" / "genre_sample_100.csv"
DEFAULT_XLSX_OUT = DEFAULT_OUT.with_suffix(".xlsx")
LAYERS: tuple[str, ...] = ("lexical", "morpho_syntactic", "word_formation", "rhetorical")
# source_text can be a whole multi-comment thread; cap it and flag the truncation.
DEFAULT_MAX_SOURCE_CHARS = 20_000
# Excel rejects control characters and caps a cell at 32,767 characters.
EXCEL_CELL_LIMIT = 32_767
_EXCEL_BAD = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

PARENT_FIELDS: tuple[str, ...] = (
    "record_id",
    "corpus_id",
    "platform_id",
    "venue_id",
    "artefact_kind",
    "urn",
)


# ═════════════════════════════════════════════════════════════════════════════
# Pure helpers (DB-free; unit-tested)
# ═════════════════════════════════════════════════════════════════════════════


def hex_prefix(seed: int, genre: str, length: int) -> str:
    """Deterministic lowercase-hex prefix of length ``length`` for one genre.

    A fixed random prefix over the uniform ``sha256`` space defines a uniform
    random subset of units that is stable across runs.
    """
    if length <= 0:
        return ""
    digest = hashlib.sha256(f"{seed}:{genre}".encode()).hexdigest()
    return digest[:length]


def choose_prefix_length(candidate_count: int, pool: int = POOL_PER_GENRE) -> int:
    """Smallest prefix length whose expected bucket is <= ``pool``.

    Returns 0 when the whole candidate set already fits in the pool (no filter).
    """
    if candidate_count <= pool:
        return 0
    length = 0
    while candidate_count / (16**length) > pool:
        length += 1
    return length


def select_sample(pool: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    """Seeded uniform sample of ``n`` rows, independent of the pool's row order."""
    if pool.empty:
        return pool.copy()
    ordered = pool.sort_values("unit_id", kind="stable")
    take = min(n, len(ordered))
    return ordered.sample(n=take, random_state=seed).reset_index(drop=True)


def _join_parts(parts: list[str | None]) -> str:
    return "\n\n".join(p for p in (str(x).strip() if x else "" for x in parts) if p)


def _comment_bodies(comments: Any, key: str = "body") -> list[str]:
    if not isinstance(comments, list):
        return []
    out = []
    for c in comments:
        if isinstance(c, dict):
            out.append(c.get(key) or c.get("text") or "")
    return out


def build_source_text(doc: dict[str, Any] | None, artefact_kind: str) -> str:
    """Reconstruct the raw source document text for one parent artefact.

    Mirrors the field shapes the extractor reads (``extractor/text_unit_extractor.py``)
    but returns the *unstripped* raw text, so a reader sees the unit in context.
    """
    if not doc:
        return ""
    kind = (artefact_kind or "").lower()
    if kind.startswith("so_"):
        return _join_parts([doc.get("title"), doc.get("text") or doc.get("body")])
    if kind in ("jira_issue", "bugzilla_issue"):
        title = doc.get("summary") or doc.get("title")
        body = doc.get("description") or doc.get("body")
        return _join_parts([title, body, *_comment_bodies(doc.get("comments"))])
    if kind in ("chat", "irc"):
        return str(doc.get("text") or doc.get("content") or "")
    if kind in ("email", "mailing_list"):
        headers = doc.get("headers") or {}
        return _join_parts([headers.get("subject"), doc.get("body_text") or doc.get("text_plain")])
    # GitHub-shaped issue / pull request (OpenMent, NumFOCUS, GitHub).
    comments = list(doc.get("comments_data") or []) + list(doc.get("issue_comments_data") or [])
    return _join_parts([doc.get("title"), doc.get("body"), *_comment_bodies(comments)])


def source_lookup(parent: dict[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    """Return (mongo collection, find_one filter) for a parent artefact."""
    kind = str(parent.get("artefact_kind") or "").lower()
    platform = str(parent.get("platform_id") or "").lower()
    record_id = parent.get("record_id")
    if not record_id:
        return None, None
    if parent.get("urn"):
        return "raw_emails", {"urn": parent["urn"]}
    if (
        kind.startswith("so_")
        or kind in ("jira_issue", "bugzilla_issue", "chat", "irc")
        or platform in ("jira", "bugzilla", "slack", "discord", "gitter", "irc", "stackoverflow")
    ):
        return "raw_external", {"record_id": record_id}
    if kind in ("email", "mailing_list"):
        return "raw_emails", {"urn": str(record_id).removeprefix("email:")}
    # GitHub-shaped issue / pull request, keyed by record_id under varying fields.
    collection = "raw_pull_requests" if kind == "pull_request" else "raw_issues"
    query = {
        "$or": [
            {"record_id": record_id},
            {"issue_key": record_id},
            {"_meta.record_id": record_id},
        ]
    }
    return collection, query


def layer_counts(layers: list[str]) -> dict[str, int]:
    """Counts keyed ``n_<layer>`` for every declared layer (zeros included)."""
    counts = {layer: 0 for layer in LAYERS}
    for layer in layers:
        if layer in counts:
            counts[layer] += 1
    return {f"n_{layer}": counts[layer] for layer in LAYERS}


def excel_safe(df: pd.DataFrame, limit: int = EXCEL_CELL_LIMIT) -> pd.DataFrame:
    """Strip control characters and cap cell length so openpyxl can write the frame."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_object_dtype(out[col]) or isinstance(out[col].dtype, pd.StringDtype):
            out[col] = out[col].map(
                lambda v: _EXCEL_BAD.sub("", v)[:limit] if isinstance(v, str) else v
            )
    return out


def row_parent(row: Any) -> dict[str, Any]:
    """Build the source-lookup dict from a sample row's ``parent_*`` columns."""
    return {field: getattr(row, f"parent_{field}", None) for field in PARENT_FIELDS}


# ═════════════════════════════════════════════════════════════════════════════
# Neo4j (read-only)
# ═════════════════════════════════════════════════════════════════════════════


def _predicate_params(rules) -> dict[str, Any]:
    return {
        "active_rules": list(rules.active),
        "rule_version": rules.version,
        "non_nk": list(rules.non_nk),
    }


def _parent_return(alias: str = "p") -> str:
    return ",\n           ".join(f"{alias}.{f} AS parent_{f}" for f in PARENT_FIELDS)


def count_candidates(corpora: list[str], rules) -> dict[str, int]:
    """Candidates per corpus: units with >=1 active non-classifier NK marker."""
    cypher = f"""
    MATCH (p:Artefact)-[:HAS_TEXT]->(u:TextUnit)
    WHERE coalesce(p.corpus_id, '') IN $corpora
    MATCH (u)-[:HAS_SIGNAL]->(s:Signal)
    WHERE {NK_SIGNAL_PREDICATE}
    RETURN p.corpus_id AS corpus_id, count(DISTINCT u.id) AS candidates
    """
    df = run_query(cypher, corpora=corpora, **_predicate_params(rules))
    return {str(r.corpus_id): int(r.candidates) for r in df.itertuples(index=False)}


def fetch_pool(prefix: str, corpora: list[str], rules, limit: int) -> pd.DataFrame:
    """Uniform random candidate pool for one genre, via a sha256 prefix filter."""
    prefix_clause = "WHERE u.sha256 STARTS WITH $prefix" if prefix else ""
    cypher = f"""
    MATCH (u:TextUnit)
    {prefix_clause}
    MATCH (p:Artefact)-[:HAS_TEXT]->(u)
    WHERE coalesce(p.corpus_id, '') IN $corpora
      AND EXISTS {{
          MATCH (u)-[:HAS_SIGNAL]->(s:Signal)
          WHERE {NK_SIGNAL_PREDICATE}
      }}
    RETURN DISTINCT u.id AS unit_id, u.sha256 AS sha256,
           {_parent_return("p")}
    LIMIT $limit
    """
    return run_query(
        cypher, prefix=prefix, corpora=corpora, limit=int(limit), **_predicate_params(rules)
    )


def explain_pool(prefix: str, corpora: list[str], rules, limit: int) -> str:
    """EXPLAIN the pool query so sha256 index use is visible (dry-run only)."""
    prefix_clause = "WHERE u.sha256 STARTS WITH $prefix" if prefix else ""
    cypher = f"""
    EXPLAIN MATCH (u:TextUnit)
    {prefix_clause}
    MATCH (p:Artefact)-[:HAS_TEXT]->(u)
    WHERE coalesce(p.corpus_id, '') IN $corpora
      AND EXISTS {{
          MATCH (u)-[:HAS_SIGNAL]->(s:Signal)
          WHERE {NK_SIGNAL_PREDICATE}
      }}
    RETURN DISTINCT u.id, u.sha256, {_parent_return("p")}
    LIMIT $limit
    """
    df = run_query(
        cypher, prefix=prefix, corpora=corpora, limit=int(limit), **_predicate_params(rules)
    )
    if df.empty:
        return "(no plan returned)"
    return str(df.iloc[:, 0].tolist())


def fetch_details(unit_ids: list[str], rules) -> pd.DataFrame:
    """Unit text/metadata + every qualifying signal for the sampled units."""
    cypher = f"""
    MATCH (p:Artefact)-[:HAS_TEXT]->(u:TextUnit)
    WHERE u.id IN $unit_ids
    OPTIONAL MATCH (u)-[:HAS_SIGNAL]->(s:Signal)
      WHERE {NK_SIGNAL_PREDICATE}
    RETURN u.id AS unit_id, u.role AS unit_role, u.position AS position,
           u.author_login AS author_login, u.created_at AS created_at,
           u.token_count AS token_count, u.sha256 AS sha256, u.text AS unit_text,
           {_parent_return("p")},
           s.layer AS layer, s.rule_id AS rule_id, s.surface_form AS surface_form
    """
    return run_query(cypher, unit_ids=list(unit_ids), **_predicate_params(rules))


# ═════════════════════════════════════════════════════════════════════════════
# MongoDB source text (read-only)
# ═════════════════════════════════════════════════════════════════════════════


async def fetch_source_texts(parents: list[dict[str, Any]], max_chars: int) -> list[dict[str, Any]]:
    """Fetch + reconstruct the raw source doc for each sampled unit's parent."""
    from settings import settings
    from storage import gather_bounded, make_mongo_client

    mongo = make_mongo_client()
    db = mongo[settings.mongo_db_name]

    async def one(parent: dict[str, Any]) -> dict[str, Any]:
        collection, query = source_lookup(parent)
        if collection is None:
            return {"source_collection": None, "source_found": False, "source_text": ""}
        doc = await db[collection].find_one(query)
        if doc is None:
            return {"source_collection": collection, "source_found": False, "source_text": ""}
        text = build_source_text(doc, str(parent.get("artefact_kind") or ""))
        return {
            "source_collection": collection,
            "source_found": True,
            "source_truncated": len(text) > max_chars,
            "source_text": text[:max_chars],
        }

    try:
        results = await gather_bounded([one(p) for p in parents], limit=16)
    finally:
        mongo.close()

    out: list[dict[str, Any]] = []
    for res in results:
        if isinstance(res, BaseException):
            logger.warning("source fetch failed: %s", res)
            out.append({"source_collection": None, "source_found": False, "source_text": ""})
        else:
            res.setdefault("source_truncated", False)
            out.append(res)
    return out


# ═════════════════════════════════════════════════════════════════════════════
# Assembly
# ═════════════════════════════════════════════════════════════════════════════


def build_rows(sample: pd.DataFrame, details: pd.DataFrame) -> pd.DataFrame:
    """One output row per sampled unit: metadata, text, parent, marker counts."""
    meta_cols = [
        "unit_id",
        "unit_role",
        "position",
        "author_login",
        "created_at",
        "token_count",
        "sha256",
        "unit_text",
        *[f"parent_{f}" for f in PARENT_FIELDS],
    ]
    base = details.drop_duplicates("unit_id").set_index("unit_id")
    rows = []
    for r in sample.itertuples(index=False):
        uid = r.unit_id
        sig = details[details.unit_id == uid]
        present = sig[sig.layer.notna()]
        info = base.loc[uid] if uid in base.index else None
        row = {"unit_id": uid}
        for col in meta_cols[1:]:
            row[col] = None if info is None else info.get(col)
        row.update(
            {
                "genre": genre_of(str(row.get("parent_corpus_id") or "")),
                "n_markers_total": int(len(present)),
                **layer_counts(list(present.layer)),
                "marker_rules": ";".join(sorted(set(present.rule_id.dropna().astype(str)))),
            }
        )
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    order = {g: i for i, g in enumerate(GENRES)}
    out["_g"] = out.genre.map(order).fillna(len(order))
    out = out.sort_values(["_g", "unit_id"], kind="stable").drop(columns="_g")
    out.insert(0, "selection_rank", out.groupby("genre", sort=False).cumcount() + 1)
    return out.reset_index(drop=True)


def attach_sources(out: pd.DataFrame, sources: list[dict[str, Any]]) -> pd.DataFrame:
    """Join source rows (aligned to ``out`` order) and present final columns."""
    out = out.copy()
    for key in ("source_collection", "source_found", "source_truncated", "source_text"):
        out[key] = [s.get(key) for s in sources]
    out["source_found"] = out["source_found"].fillna(False).astype(bool)
    out["source_truncated"] = out["source_truncated"].fillna(False).astype(bool)
    final = [
        "selection_rank",
        "genre",
        "corpus_id",
        "platform_id",
        "venue_id",
        "artefact_kind",
        "record_id",
        "unit_id",
        "unit_role",
        "position",
        "author_login",
        "created_at",
        "token_count",
        "sha256",
        "unit_text",
        "source_collection",
        "source_found",
        "source_truncated",
        "source_text",
        "n_markers_total",
        *(f"n_{layer}" for layer in LAYERS),
        "marker_rules",
    ]
    out["corpus_id"] = out["parent_corpus_id"]
    out["platform_id"] = out["parent_platform_id"]
    out["venue_id"] = out["parent_venue_id"]
    out["artefact_kind"] = out["parent_artefact_kind"]
    out["record_id"] = out["parent_record_id"]
    return out[final]


# Column widths (characters) for a readable sheet; unknown columns get 14.
_EXCEL_WIDTHS = {
    "selection_rank": 9,
    "genre": 12,
    "corpus_id": 22,
    "platform_id": 12,
    "venue_id": 22,
    "artefact_kind": 14,
    "record_id": 32,
    "unit_id": 42,
    "unit_role": 12,
    "position": 8,
    "author_login": 20,
    "created_at": 16,
    "token_count": 11,
    "sha256": 18,
    "unit_text": 55,
    "source_collection": 16,
    "source_found": 12,
    "source_truncated": 16,
    "source_text": 85,
    "n_markers_total": 15,
    "marker_rules": 45,
}


def write_workbook(df: pd.DataFrame, path: str | Path) -> Path:
    """Write the sample to a formatted .xlsx (frozen header, wrapped text)."""
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = excel_safe(df)
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        safe.to_excel(writer, index=False, sheet_name="sample")
        ws = writer.sheets["sample"]
        ws.freeze_panes = "A2"
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for i, col in enumerate(safe.columns, start=1):
            ws.column_dimensions[get_column_letter(i)].width = _EXCEL_WIDTHS.get(
                str(col), max(14, min(len(str(col)) + 2, 40))
            )
            if col in ("unit_text", "source_text"):
                for cell in ws[get_column_letter(i)][1:]:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
    return path


# ═════════════════════════════════════════════════════════════════════════════
# Driver
# ═════════════════════════════════════════════════════════════════════════════


def draw_pools(
    rules, corpora_map: dict[str, list[str]], seed: int, pool: int, dry_run: bool
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Count candidates and draw one uniform pool per genre."""
    all_corpora = sorted({c for cs in corpora_map.values() for c in cs})
    logger.info("counting candidates across %d in-scope corpora ...", len(all_corpora))
    counts = count_candidates(all_corpora, rules)
    pools: list[pd.DataFrame] = []
    per_genre_counts: dict[str, int] = {}
    for genre in GENRES:
        corpora = corpora_map.get(genre, [])
        n = sum(counts.get(c, 0) for c in corpora)
        per_genre_counts[genre] = n
        length = choose_prefix_length(n, pool)
        prefix = hex_prefix(seed, genre, length)
        limit = max(pool, TARGET_PER_GENRE) * (POOL_LIMIT_MULT if length else 1)
        if dry_run and length:
            logger.info("EXPLAIN %s: %s", genre, explain_pool(prefix, corpora, rules, limit))
        pool_df = fetch_pool(prefix, corpora, rules, limit)
        pool_df["genre"] = genre
        logger.info(
            "genre %-12s candidates=%-10d prefix_len=%d pool=%d", genre, n, length, len(pool_df)
        )
        pools.append(pool_df)
    pool_all = pd.concat(pools, ignore_index=True) if pools else pd.DataFrame()
    return pool_all, per_genre_counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--xlsx-out", type=Path, default=DEFAULT_XLSX_OUT)
    parser.add_argument(
        "--no-xlsx", action="store_true", help="write the CSV only (skip the .xlsx export)."
    )
    parser.add_argument("--per-genre", type=int, default=TARGET_PER_GENRE)
    parser.add_argument("--pool", type=int, default=POOL_PER_GENRE)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--max-source-chars", type=int, default=DEFAULT_MAX_SOURCE_CHARS)
    parser.add_argument(
        "--no-marker-rules",
        action="store_true",
        help="drop the marker_rules column (semicolon-joined rule ids).",
    )
    parser.add_argument("--dry-run", action="store_true", help="counts + pools only; no CSV.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    rules = load_rule_sets()
    logger.info("active rules: %d (pattern set v%s)", len(rules.active), rules.version)
    corpora_map = corpora_by_genre()
    pool_all, counts = draw_pools(rules, corpora_map, args.seed, args.pool, args.dry_run)
    logger.info("candidate counts by genre: %s", counts)
    if args.dry_run:
        print("DRY RUN — candidates / pool / selected per genre:")
        for genre in GENRES:
            sub = pool_all[pool_all.genre == genre] if len(pool_all) else pool_all
            selected = min(args.per_genre, len(sub))
            print(
                f"  {genre:<12} candidates={counts.get(genre, 0):>10,} "
                f"pool={len(sub):>5} selected={selected}"
            )
        return 0

    selected = []
    for genre in GENRES:
        sub = pool_all[pool_all.genre == genre] if len(pool_all) else pool_all
        if len(sub) < args.per_genre:
            logger.warning(
                "genre %s: pool %d < %d; sample is short.", genre, len(sub), args.per_genre
            )
        selected.append(select_sample(sub, args.per_genre, args.seed))
    sample = pd.concat(selected, ignore_index=True) if selected else pd.DataFrame()
    logger.info("selected units: %d", len(sample))
    if sample.empty:
        logger.error("no units sampled; nothing written.")
        return 1

    details = fetch_details(list(sample.unit_id), rules)
    out = build_rows(sample, details)
    parents = [row_parent(r) for r in out.itertuples(index=False)]
    sources = asyncio.run(fetch_source_texts(parents, args.max_source_chars))
    out = attach_sources(out, sources)
    if args.no_marker_rules:
        out = out.drop(columns=["marker_rules"])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    logger.info(
        "wrote %d rows to %s (source_found=%d/%d)",
        len(out),
        args.out,
        int(out.source_found.sum()),
        len(out),
    )
    if not args.no_xlsx:
        xlsx_path = write_workbook(out, args.xlsx_out)
        logger.info("wrote xlsx to %s", xlsx_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
