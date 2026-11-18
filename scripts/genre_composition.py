#!/usr/bin/env python3
"""
scripts/genre_composition.py

Extract the per-(dataset, layer, subcategory, rule) NK-signal composition that
backs the composition and fingerprint figures in
``notebooks/02b_rq_analysis.ipynb`` (the "Genre & dataset composition of
linguistic ignorance" section).

What it produces
----------------
One cached CSV of *counts* — no shares, no effects, no thresholds. The notebook
derives all normalisation from it, so figure iteration never re-queries Neo4j.
Two granularities share one file (``granularity`` column):

* ``rule``        — one row per (dataset, layer, subcategory, rule_id) with
                    ``n_signals`` (hits).
* ``subcategory`` — one row per (dataset, layer, subcategory); ``n_signals`` is
                    the exact sum of its rule rows, and ``n_units`` is the count
                    of *distinct* TextUnits carrying >=1 signal of the
                    subcategory (only populated with ``--with-units``).

Why this lives outside the notebook
-----------------------------------
Morpho-syntactic alone is ~84 M Signals and the two 14 M-unit corpora
(``alternative-jira``, ``curated-email-code-reviews``) dominate the pull, so the
full refresh is a multi-minute job (AGENTS.md §5.11) that is run once and cached.

Query shape (do not "simplify")
-------------------------------
The notebook's historical shape — ``MATCH (u)-[:HAS_SIGNAL]->(s:Signal {layer:...})``
— seeds the planner from the ``Signal(layer)`` index and hangs on morpho. This
module instead starts from the indexed ``Artefact.source_corpus`` with a scalar
corpus equality and keeps every layer predicate in ``WHERE``:

    MATCH (p:Artefact {source_corpus: $corpus})-[:HAS_TEXT]->(u:TextUnit)
          -[:HAS_SIGNAL]->(s:Signal)
    WHERE s.layer IN $layers AND ...

Verified timings on the live store: disco ≈ 2 s, alternative-jira ≈ 50 s for all
three rule layers in one pass. ``s.layer IN $layers`` is safe here because the
seed is the indexed corpus; inlining ``{layer: ...}`` on the target node is not.

Realises the signal taxonomies of FRAMEWORK_DESIGN.md §4.3 over the v0.3 curated
scope (FRAMEWORK_DESIGN.md §12) and the genre-composition reading of Sub-RQ 1
(REFINED_RQS_v0.3.md §2). Read-only: writes a CSV, never Neo4j/Mongo/Redis.

The canonical stale-span exclusions and sandbox guard are imported verbatim from
``scripts/openment_roles.py`` so this analyser cannot drift from the notebook.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger("scripts.genre_composition")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.corpus_census import GENRE_BY_CORPUS  # noqa: E402
from scripts.openment_roles import (  # noqa: E402
    STALE_SIGNAL_EXCLUSION,
    RuleSets,
    _sandbox_clause,
    load_rule_sets,
    run_query,
)

OUT_DIR = PROJECT_ROOT / "notebooks"
DEFAULT_OUT = OUT_DIR / "genre_composition_counts.csv"

# The four rule layers. `classifier` is excluded by construction: it is a binary
# verdict, not an NK subcategory.
LAYERS: tuple[str, ...] = ("lexical", "morpho_syntactic", "word_formation", "rhetorical")

# ── Genre naming (2026-10-15) ────────────────────────────────────────────────
# 02b uses tracker/email/chat/qa; scripts/corpus_census.py (the canonical source
# of truth) uses tracker/review_email/chat/qa. The user chose to keep 02b's
# names here, so `review_email` is aliased to `email` on ingest.
# TODO(design-review): 02b's own registry is stale relative to corpus_census.py
# (see CHANGELOG 2026-10-03/2026-10-07); reconcile the two in a dedicated pass.
GENRE_ALIAS: dict[str, str] = {"review_email": "email"}
GENRES: tuple[str, ...] = ("tracker", "email", "chat", "qa")


def genre_of(corpus_id: str) -> str:
    """02b-compatible genre for a curated corpus_id; 'EXCLUDED' out of scope."""
    raw = GENRE_BY_CORPUS.get(corpus_id, "EXCLUDED")
    return GENRE_ALIAS.get(raw, raw)


def corpora_by_genre() -> dict[str, list[str]]:
    """Invert the registry into genre → sorted corpus ids (02b genre names)."""
    out: dict[str, list[str]] = {g: [] for g in GENRES}
    for corpus_id in GENRE_BY_CORPUS:
        out.setdefault(genre_of(corpus_id), []).append(corpus_id)
    for corpora in out.values():
        corpora.sort()
    return out


def in_scope_corpora() -> list[str]:
    """Every corpus_id with a genre in :data:`GENRES`, sorted."""
    return sorted(c for c in GENRE_BY_CORPUS if genre_of(c) in GENRES)


# ═════════════════════════════════════════════════════════════════════════════
# Cypher (read-only)
# ═════════════════════════════════════════════════════════════════════════════


def composition_predicate() -> str:
    """The NK predicate for this analysis, with ``$rule_ids`` as the rule set.

    Mirrors ``NK_SIGNAL_PREDICATE`` in ``openment_roles.py`` but takes the rule
    set from ``$rule_ids`` (so the caller can pass active-only *or*
    active+candidate) and fixes the layer set to the four rule layers.
    """
    return f"""
        s.layer IN $layers
        AND s.rule_version = $rule_version
        AND s.rule_id IN $rule_ids
        AND NOT coalesce(s.subcategory, '') IN $non_nk
        {STALE_SIGNAL_EXCLUSION}
    """


def _params(rules: RuleSets, rule_ids: list[str], layers: tuple[str, ...]) -> dict[str, Any]:
    return {
        "rule_version": rules.version,
        "rule_ids": rule_ids,
        "non_nk": list(rules.non_nk),
        "layers": list(layers),
    }


def _rule_cypher() -> str:
    return f"""
    MATCH (p:Artefact {{source_corpus: $corpus}})-[:HAS_TEXT]->(u:TextUnit)
          -[:HAS_SIGNAL]->(s:Signal)
    WHERE {composition_predicate()}{_sandbox_clause("u")}
    RETURN s.layer AS layer, s.subcategory AS subcategory, s.rule_id AS rule_id,
           count(*) AS n_signals
    """


def _unit_cypher() -> str:
    return f"""
    MATCH (p:Artefact {{source_corpus: $corpus}})-[:HAS_TEXT]->(u:TextUnit)
          -[:HAS_SIGNAL]->(s:Signal)
    WHERE {composition_predicate()}{_sandbox_clause("u")}
    RETURN s.layer AS layer, s.subcategory AS subcategory,
           count(DISTINCT u) AS n_units
    """


# ═════════════════════════════════════════════════════════════════════════════
# Pure helpers (DB-free; unit-tested)
# ═════════════════════════════════════════════════════════════════════════════

RULE_COLUMNS: tuple[str, ...] = (
    "dataset",
    "genre",
    "layer",
    "subcategory",
    "rule_id",
    "granularity",
    "n_signals",
    "n_units",
)
SUB_COLUMNS: tuple[str, ...] = RULE_COLUMNS


def _empty(cols: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(cols))


def tag_corpus(df: pd.DataFrame, corpus_id: str) -> pd.DataFrame:
    """Attach ``dataset``/``genre`` and stamp the ``rule`` granularity."""
    out = df.copy()
    out.insert(0, "dataset", corpus_id)
    out.insert(1, "genre", genre_of(corpus_id))
    out["rule_id"] = out["rule_id"].fillna("").astype(str)
    out["granularity"] = "rule"
    if "n_units" not in out.columns:
        out["n_units"] = pd.NA
    return out[[c for c in RULE_COLUMNS if c in out.columns]]


def rule_rows_to_subcategory(rule_df: pd.DataFrame) -> pd.DataFrame:
    """Collapse rule rows to subcategory level by summing ``n_signals``.

    Hits are additive because every Signal belongs to exactly one
    ``(layer, subcategory, rule_id)``. Distinct-unit counts are **not** additive
    and are left NA here; use :func:`attach_subcategory_units` for those.
    """
    if rule_df.empty:
        return _empty(SUB_COLUMNS)
    grp = rule_df.groupby(["dataset", "genre", "layer", "subcategory"], as_index=False).agg(
        n_signals=("n_signals", "sum")
    )
    grp["rule_id"] = ""
    grp["granularity"] = "subcategory"
    grp["n_units"] = pd.NA
    return grp[list(SUB_COLUMNS)]


def attach_subcategory_units(sub_df: pd.DataFrame, units_df: pd.DataFrame) -> pd.DataFrame:
    """Left-join distinct-unit counts (from the second pass) onto subcategory rows."""
    out = sub_df.copy()
    if units_df.empty:
        return out
    merged = out.drop(columns=["n_units"]).merge(
        units_df[["dataset", "layer", "subcategory", "n_units"]],
        on=["dataset", "layer", "subcategory"],
        how="left",
    )
    merged["n_units"] = merged["n_units"].astype("Int64")
    return merged[list(SUB_COLUMNS)]


# ═════════════════════════════════════════════════════════════════════════════
# Composition shares and distinctiveness effects
# ═════════════════════════════════════════════════════════════════════════════


def composition_shares(comp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Per-dataset layer shares, equal-weight genre composition and reference.

    Returns ``(c, P, R)``:

    * ``c``  — dataset × layer × subcategory: ``n_signals``, ``N`` (sum of the
      layer's subcategory hits — a *subcategory-incidence* count, not distinct
      units), and ``p = n_signals / N``.
    * ``P``  — genre × layer × subcategory: unweighted mean of ``p`` over the
      genre's datasets.
    * ``R``  — layer × subcategory: unweighted mean of ``P`` over the four
      genres (the reference profile).
    """
    sub = comp[comp.granularity == "subcategory"].copy()
    c = sub.groupby(["dataset", "genre", "layer", "subcategory"], as_index=False).agg(
        n_signals=("n_signals", "sum")
    )
    c["N"] = c.groupby(["dataset", "layer"])["n_signals"].transform("sum")
    c["p"] = c["n_signals"] / c["N"].replace(0, np.nan)
    P = c.groupby(["genre", "layer", "subcategory"], as_index=False).agg(
        P=("p", "mean"), n_datasets=("dataset", "nunique")
    )
    R = P.groupby(["layer", "subcategory"], as_index=False).agg(R=("P", "mean"))
    return c, P, R


def distinctiveness(
    c: pd.DataFrame,
    R: pd.DataFrame,
    *,
    alpha: float = 10.0,
    min_count: int = 30,
    consistency: float = float(np.log2(1.5)),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dataset effects ``e`` and genre effects ``E`` (both log2 vs the reference).

    Returns ``(ds, ge)``. ``ge`` carries the per-genre verdict columns
    ``consistent_driver`` / ``single_dataset`` used to pick filled ● / open ○ /
    square ■ markers. (``P`` is not needed: the genre mean of ``p_tilde`` is
    computed directly from ``c``.)

    * ``e[d] = log2( p_tilde[d] / R )`` with Dirichlet smoothing
      ``p_tilde = (n + alpha*R) / (N + alpha)``.
    * ``E[g] = log2( mean_{d in g} p_tilde / R )``.
    * ``low_count`` marks cells with ``n_signals < min_count``.
    * ``consistent_driver`` requires k >= 2, ``|E| >= consistency``, every
      dataset ``e`` sharing the sign of ``E``, and no low-count dataset cell.
    """
    r = R.rename(columns={"R": "R"})
    ds = c.merge(r, on=["layer", "subcategory"], how="left")
    ds["p_tilde"] = (ds["n_signals"] + alpha * ds["R"]) / (ds["N"] + alpha)
    ds["e"] = np.log2(ds["p_tilde"] / ds["R"])
    ds["low_count"] = ds["n_signals"] < min_count

    ge = ds.groupby(["genre", "layer", "subcategory"], as_index=False).agg(
        E_p_tilde=("p_tilde", "mean"),
        R=("R", "first"),
        e_min=("e", "min"),
        e_max=("e", "max"),
        n_datasets=("dataset", "nunique"),
        n_low_count=("low_count", "sum"),
    )
    ge["E"] = np.log2(ge["E_p_tilde"] / ge["R"])
    ge["single_dataset"] = ge["n_datasets"] < 2
    same_sign = np.sign(ge["e_min"]) == np.sign(ge["e_max"])
    ge["consistent_driver"] = (
        (~ge["single_dataset"])
        & (ge["E"].abs() >= consistency)
        & same_sign
        & (ge["n_low_count"] == 0)
    )
    return ds, ge


# ═════════════════════════════════════════════════════════════════════════════
# Driver
# ═════════════════════════════════════════════════════════════════════════════


def extract_corpus(
    corpus_id: str,
    rules: RuleSets,
    rule_ids: list[str],
    layers: tuple[str, ...],
    *,
    with_units: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """One corpus → (rule-level rows, subcategory-level rows with distinct units)."""
    t0 = time.time()
    params = _params(rules, rule_ids, layers)
    raw = run_query(_rule_cypher(), corpus=corpus_id, **params)
    rule_df = tag_corpus(raw, corpus_id) if not raw.empty else _empty(RULE_COLUMNS)

    sub_df = rule_rows_to_subcategory(rule_df)
    if with_units and not rule_df.empty:
        units = run_query(_unit_cypher(), corpus=corpus_id, **params)
        units = units.assign(dataset=corpus_id)
        units["n_units"] = pd.to_numeric(units["n_units"], errors="coerce").astype("Int64")
        sub_df = attach_subcategory_units(sub_df, units)
    logger.info(
        "  %-32s %5.1fs  rules=%-5d subcats=%-3d signals=%s",
        corpus_id,
        time.time() - t0,
        len(rule_df),
        len(sub_df),
        int(rule_df.n_signals.sum()) if not rule_df.empty else 0,
    )
    return rule_df, sub_df


def extract_all(
    rules: RuleSets,
    rule_ids: list[str],
    layers: tuple[str, ...],
    corpora: list[str],
    *,
    with_units: bool,
) -> pd.DataFrame:
    """Pull every corpus and return one tidy long frame (both granularities)."""
    rule_frames, sub_frames = [], []
    for corpus_id in corpora:
        rule_df, sub_df = extract_corpus(corpus_id, rules, rule_ids, layers, with_units=with_units)
        if not rule_df.empty:
            rule_frames.append(rule_df)
        if not sub_df.empty:
            sub_frames.append(sub_df)
    frames = [f for f in (*rule_frames, *sub_frames) if not f.empty]
    if not frames:
        return _empty(RULE_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    out["n_signals"] = pd.to_numeric(out["n_signals"], errors="coerce").fillna(0).astype(int)
    out["n_units"] = pd.to_numeric(out["n_units"], errors="coerce").astype("Int64")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ruleset",
        choices=("valid", "active"),
        default="valid",
        help="'valid' = active+candidate (needed for word_formation, which has "
        "no active rules); 'active' = the RQ1/RQ2 headline rule set.",
    )
    parser.add_argument("--version", default=None, help="pattern_set_version (default: settings).")
    parser.add_argument("--layers", default=",".join(LAYERS), help="comma-separated layers.")
    parser.add_argument("--with-units", action="store_true", help="add a distinct-unit pass.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true", help="print the plan; no DB write.")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    layers = tuple(layer.strip() for layer in args.layers.split(",") if layer.strip())
    if not layers:
        parser.error("--layers must name at least one layer")

    rules = load_rule_sets(version=args.version)
    rule_ids = list(rules.valid if args.ruleset == "valid" else rules.active)
    corpora = in_scope_corpora()

    logger.info(
        "ruleset=%s (%d rules), version=%s, layers=%s, corpora=%d, with_units=%s",
        args.ruleset,
        len(rule_ids),
        rules.version,
        layers,
        len(corpora),
        args.with_units,
    )
    by_genre = corpora_by_genre()
    for genre in GENRES:
        logger.info("  %-8s %s", genre, ", ".join(by_genre.get(genre, [])))

    if args.dry_run:
        print("\nDRY RUN — nothing queried. Query shape:\n")
        print(_rule_cypher().strip())
        print("\nCorpora:")
        for genre in GENRES:
            for corpus_id in by_genre.get(genre, []):
                print(f"  {genre:<8} {corpus_id}")
        return 0

    logger.info("extracting (multi-minute on the full store; see AGENTS.md §5.11) ...")
    t0 = time.time()
    out = extract_all(rules, rule_ids, layers, corpora, with_units=args.with_units)
    if out.empty:
        logger.error("no NK signals found for any corpus; nothing written.")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(args.out, index=False)
    logger.info(
        "wrote %d rows to %s in %.1fs (rules=%d, subcats=%d)",
        len(out),
        args.out,
        time.time() - t0,
        int((out.granularity == "rule").sum()),
        int((out.granularity == "subcategory").sum()),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
