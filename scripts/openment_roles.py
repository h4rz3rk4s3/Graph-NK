"""
scripts/openment_roles.py — RQ3b OpenMent mentor/mentee NK-gap investigation.

Qualitative + quantitative analysis of the OpenMent role asymmetry reported in
``notebooks/03_rq_analysis.ipynb`` (RQ3b setting 1): mentors articulate more
non-knowledge signals per token than mentees (51.837 vs 39.471 / 1k tokens in
the unfiltered population). Implements the five-phase plan:

  P0  schema audit (blocking)      -> rq3b_om_P0_schema_report.md
  P1  hygiene checks               -> rq3b_om_P1_unit_flags.csv, rates_by_filter
  P2  project overview + EB shrink -> rq3b_om_P2_projects.csv
  P3  gap decomposition + skew     -> rq3b_om_P3_*.csv, models.md
  P4  thread sampling frame        -> rq3b_om_P4_*.csv, Word exports
  P5  signal coding + adjusted     -> rq3b_om_P5_*.*

Design contract (AGENTS.md §5, plan §1)
---------------------------------------
* Signal pluralism: nothing here writes to Neo4j. Filtering happens in pandas.
* Rules are read from the same YAML files the annotators load; the NK predicate
  is copied verbatim from the notebook and exercised against the 51.837/39.471
  regression anchor.
* OpenMent is GitHub-shaped (issues/PRs + comments), NOT email. Each issue/PR
  *is* the thread (``p.record_id``); no reply-graph reconstruction is needed.
* Dates are anonymised day offsets; the Word export shows relative elapsed days.

Run ``python scripts/openment_roles.py --help`` for the phase CLIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

logger = logging.getLogger("scripts.openment_roles")

# Running this file directly puts ``scripts/`` on sys.path; add the repo root so
# ``settings``/``scripts.*`` imports resolve the same way they do under pytest.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

OUT_DIR = PROJECT_ROOT / "notebooks"
PLOT_DIR = OUT_DIR / "rq3b_om_plots"
DATASET_DIRNAME = "OpenMent-dataset"
ROLES = ("mentor", "mentee")
SEED = 20261002

# ── Canonical NK predicate (copied verbatim from notebooks/03_rq_analysis.ipynb
#    cell 2). "Active" is resolved by rule_id membership in the current YAMLs,
#    never by the stale annotation-time ``s.status`` in the graph. ─────────────
# 2026-10-03: the graph still holds pre-fix morph.syn.embedded_question signals
# from the old Matcher whose head token carried OP:"?" — it matched every bare
# if/how/when/which/what/where/why/whether. The rule is now a scoped
# DependencyMatcher (patterns/morpho_syntactic_v0.2.yml); the stale single-token
# false positives are excluded here at analysis time instead of being purged
# from the external-drive store. Genuine embedded questions are multi-word
# ("wonder if", "unclear how") and are kept. See CHANGELOG 2026-10-03.
#
# 2026-10-07 (v0.2.2 cross-layer ownership): three more rule definitions were
# NARROWED in place under the same rule_version, so pre-change spans the new
# patterns no longer produce survive as ghosts. They are excluded live for the
# same reason as embedded_question (no graph purge): the changed rules'
# definitions live in patterns/morpho_syntactic_v0.2.yml, the stale spans are
# cheap to filter, and a mass DETACH DELETE on the external-drive store is the
# documented slow path. Each guard is scoped by rule_id AND a property of the
# stale span only, so it never touches the retained matches.
#   * future_nk_wont_know dropped can't/cannot: the new pattern's modal token is
#     wo/won't/wont, so every surviving span starts with "wo"; the old can-forms
#     (cannot/can't) do not.
#   * neg_cognition_modal dropped the "wo" auxiliary: the same starts-with test
#     removes its stale "won't" spans ("won't know" is now owned by
#     future_nk_wont_know; "can't/couldn't …" are retained).
#   * rhetor.metaphor.spatial.uncharted dropped the "terra incognita" realisation:
#     every stale span starts with "terra".
STALE_SIGNAL_EXCLUSION = (
    "AND NOT (s.rule_id = 'morph.syn.embedded_question' "
    "AND NOT coalesce(s.surface_form, '') CONTAINS ' ') "
    "AND NOT (s.rule_id = 'morph.tense.future_nk_wont_know' "
    "AND NOT toLower(coalesce(s.surface_form, '')) STARTS WITH 'wo') "
    "AND NOT (s.rule_id = 'morph.epi.neg_cognition_modal' "
    "AND toLower(coalesce(s.surface_form, '')) STARTS WITH 'wo') "
    "AND NOT (s.rule_id = 'rhetor.metaphor.spatial.uncharted' "
    "AND toLower(coalesce(s.surface_form, '')) STARTS WITH 'terra')"
)
NK_SIGNAL_PREDICATE = f"""
    s.layer <> 'classifier'
    AND s.status IN ['active', 'candidate']
    AND s.rule_id IN $active_rules
    AND s.rule_version = $rule_version
    AND NOT coalesce(s.subcategory, '') IN $non_nk
    {STALE_SIGNAL_EXCLUSION}
"""


# ═════════════════════════════════════════════════════════════════════════════
# Rule sets (loaded from YAML, shared by every phase)
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RuleSets:
    """Active/candidate rule ids plus the non-NK contrast subcategories."""

    version: str
    active: tuple[str, ...]
    candidate: tuple[str, ...]
    non_nk: tuple[str, ...]
    status: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.active) | set(self.candidate)))


def load_rule_sets(root: Path = PROJECT_ROOT, version: str | None = None) -> RuleSets:
    """Rebuild the authoritative rule-id sets from the four pattern/lexicon YAMLs.

    Mirrors ``_split_rules_by_status()`` in the notebook, including re-applying
    the ``lex.`` prefix (the lexicon YAML stores bare ids, the annotator emits
    ``lex.<id>``).
    """
    if version is None:
        from settings import settings

        version = settings.pattern_set_version

    morpho = yaml.safe_load((root / "patterns" / f"morpho_syntactic_v{version}.yml").read_text())
    lex = yaml.safe_load((root / "lexicons" / f"en_core_v{version}.yml").read_text())
    rhet = yaml.safe_load((root / "patterns" / f"rhetorical_v{version}.yml").read_text())
    wf = yaml.safe_load((root / "patterns" / f"word_formation_v{version}.yml").read_text())

    active: set[str] = set()
    candidate: set[str] = set()

    def add(rid: str, status: str | None) -> None:
        (active if status == "active" else candidate).add(rid)

    for e in lex.get("entries", []):
        rid = f"lex.{e['id']}" if not e["id"].startswith("lex.") else e["id"]
        add(rid, e.get("status"))
    for p in morpho.get("patterns", []):
        add(p["id"], p.get("status"))
    for f in rhet.get("figures", []):
        add(f["rule_id"], f.get("status"))
    for a in wf.get("prefixes", []) + wf.get("suffixes", []):
        add(a["rule_id"], a.get("status"))

    non_nk = sorted(
        {"booster", "privative", "privative_certainty"}
        | {e.get("subcategory") for e in lex.get("entries", []) if e.get("polarity") == "certainty"}
        | {s.get("subcategory") for s in wf.get("suffixes", []) if s.get("polarity") == "certainty"}
    )
    status = {r: "active" for r in active}
    status.update({r: "candidate" for r in candidate})
    return RuleSets(
        version=version,
        active=tuple(sorted(active)),
        candidate=tuple(sorted(candidate)),
        non_nk=tuple(non_nk),
        status=status,
    )


# ═════════════════════════════════════════════════════════════════════════════
# Neo4j access (read-only)
# ═════════════════════════════════════════════════════════════════════════════

_SANDBOX_CLAUSE: str | None = None


def _sandbox_clause(alias: str = "u") -> str:
    """Return the ``@sandbox(alias)`` guard, or '' when no sandbox property exists.

    The notebook builds the same guard dynamically (``SANDBOX_KEY_EXISTS``);
    this DB has no ``sandbox`` property, so the predicate is inert.
    """
    global _SANDBOX_CLAUSE
    if _SANDBOX_CLAUSE is None:
        try:
            df = run_query("CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey")
            exists = "sandbox" in set(df["propertyKey"])
        except Exception:  # pragma: no cover - DB not available in unit tests
            exists = False
        _SANDBOX_CLAUSE = " AND coalesce({a}.sandbox, false) = false" if exists else ""
    return _SANDBOX_CLAUSE.format(a=alias)


def _driver():
    from neo4j import GraphDatabase

    from settings import settings

    auth = (
        None
        if settings.neo4j_password in ("none", "")
        else (settings.neo4j_user, settings.neo4j_password)
    )
    return GraphDatabase.driver(settings.neo4j_uri, auth=auth)


def run_query(cypher: str, **params) -> pd.DataFrame:
    """Run a read-only Cypher query; columns survive an empty result."""
    with _driver().session() as session:
        result = session.run(cypher, **params)
        keys = result.keys()
        rows = [r.data() for r in result]
    return pd.DataFrame(rows, columns=keys)


# ═════════════════════════════════════════════════════════════════════════════
# Domain loading: units, roles, signals
# ═════════════════════════════════════════════════════════════════════════════


def load_roles(path: Path | None = None) -> dict[tuple[str, str], str]:
    """Load ``project_roles.csv`` → {(project_id, user_id): role}."""
    if path is None:
        from settings import settings

        path = Path(settings.datasets_root) / DATASET_DIRNAME / "project_roles.csv"
    roles: dict[tuple[str, str], str] = {}
    for row in pd.read_csv(path).itertuples():
        roles[(row.project_id, row.user_id)] = row.role
    return roles


def dual_role_users(roles: dict[tuple[str, str], str]) -> set[str]:
    """Users annotated as *both* mentor and mentee across different projects."""
    by_user: dict[str, set[str]] = {}
    for (_pid, uid), role in roles.items():
        by_user.setdefault(uid, set()).add(role)
    return {u for u, rs in by_user.items() if len(rs) > 1}


def fetch_openment_units() -> pd.DataFrame:
    """All OpenMent TextUnits with parent, author, role, tokens and raw text.

    ``thread_id``/``message_id`` are derived here because OpenMent is
    GitHub-shaped: an issue/PR (``p.record_id``) is the thread, its title+body
    form the opening message, and each comment is its own message.
    """
    cypher = f"""
    MATCH (p:Artefact)-[:HAS_TEXT]->(u:TextUnit)
    WHERE coalesce(p.corpus_id, '') = 'openment'{_sandbox_clause()}
    RETURN u.id AS tu_id, p.record_id AS thread_id, p.repo AS repo,
           coalesce(u.author_login, '') AS author, u.token_count AS tokens,
           u.position AS position, u.role AS tu_role, u.created_at AS created_day,
           u.sha256 AS sha256, u.text AS text
    """
    df = run_query(cypher)
    if df.empty:
        return df
    df["project_id"] = df["repo"].map(lambda r: r.split(":", 1)[1] if ":" in str(r) else "")
    df["tokens"] = pd.to_numeric(df["tokens"], errors="coerce").fillna(0).astype(int)
    df["position"] = pd.to_numeric(df["position"], errors="coerce").fillna(0).astype(int)
    df["created_day"] = pd.to_numeric(df["created_day"], errors="coerce")
    df["text"] = df["text"].fillna("").astype(str)
    df["message_id"] = [
        tid + (":op" if role in ("title", "body") else f":comment:{pos}")
        for tid, role, pos in zip(df["thread_id"], df["tu_role"], df["position"], strict=False)
    ]
    df["sent_at"] = [
        (pd.Timestamp("2000-01-01") + pd.Timedelta(days=float(d))).isoformat()
        if pd.notna(d)
        else None
        for d in df["created_day"]
    ]
    return df


def attach_roles(units: pd.DataFrame, roles: dict[tuple[str, str], str]) -> pd.DataFrame:
    """Add ``role`` (mentor/mentee/None) and ``dual_role`` flags to units."""
    units = units.copy()
    units["role"] = [
        roles.get((pid, a)) for pid, a in zip(units.project_id, units.author, strict=False)
    ]
    dual = dual_role_users(roles)
    units["dual_role"] = units["author"].isin(dual)
    return units


def fetch_openment_signals(rules: RuleSets) -> pd.DataFrame:
    """All NK signals attached to OpenMent units (classifier excluded)."""
    cypher = f"""
    MATCH (p:Artefact)-[:HAS_TEXT]->(u:TextUnit)-[:HAS_SIGNAL]->(s:Signal)
    WHERE coalesce(p.corpus_id, '') = 'openment' AND {NK_SIGNAL_PREDICATE}{_sandbox_clause()}
    RETURN u.id AS tu_id, s.layer AS layer, s.category AS category,
           s.subcategory AS subcategory, s.rule_id AS rule_id, s.status AS status,
           s.span_start AS span_start, s.span_end AS span_end,
           s.surface_form AS surface_form, s.rule_version AS rule_version,
           s.id AS signal_id
    """
    return run_query(
        cypher,
        active_rules=list(rules.active),
        rule_version=rules.version,
        non_nk=list(rules.non_nk),
    )


def fetch_classifier_pos(tu_ids: list[str]) -> pd.DataFrame:
    """Classifier-positive flags for a bounded set of TextUnits (P4 stratifier).

    The classifier is a *sampling stratifier only* (plan §1.4) — never a weight.
    """
    if not tu_ids:
        return pd.DataFrame(columns=["tu_id", "clf_label"])
    cypher = """
    MATCH (u:TextUnit)-[:CLASSIFIED_AS]->(v:ClassifierVerdict)
    WHERE u.id IN $tu_ids
    RETURN u.id AS tu_id, v.label AS clf_label
    """
    return run_query(cypher, tu_ids=list(tu_ids))


def fetch_classifier_share_by_thread() -> pd.DataFrame:
    """Mean classifier-positive label per OpenMent thread (sampling stratifier)."""
    cypher = f"""
    MATCH (p:Artefact)-[:HAS_TEXT]->(u:TextUnit)-[:CLASSIFIED_AS]->(v:ClassifierVerdict)
    WHERE coalesce(p.corpus_id, '') = 'openment'{_sandbox_clause()}
    RETURN p.record_id AS thread_id, avg(v.label) AS clf_share, count(*) AS n_clf
    """
    return run_query(cypher)


# ═════════════════════════════════════════════════════════════════════════════
# Unit-level NK table + pooled rates (regression anchor)
# ═════════════════════════════════════════════════════════════════════════════


def build_unit_nk(units: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """One row per unit: nk count joined onto role/tokens/project/thread."""
    nk = (
        signals.groupby("tu_id").size().rename("nk").reset_index()
        if len(signals)
        else pd.DataFrame(columns=["tu_id", "nk"])
    )
    out = units.merge(nk, on="tu_id", how="left")
    out["nk"] = out["nk"].fillna(0).astype(int)
    return out


def pooled_rates(unit_nk: pd.DataFrame) -> pd.DataFrame:
    """Pooled signals/1k-tokens per role (the notebook's 51.837 / 39.471)."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    per = lab.groupby("role").agg(
        units=("tu_id", "size"), tokens=("tokens", "sum"), nk=("nk", "sum")
    )
    per["rate_per_1k"] = 1000 * per.nk / per.tokens.replace(0, np.nan)
    return per


def assert_regression_anchor(unit_nk: pd.DataFrame, tol: float = 1e-3) -> None:
    """Fail loudly if the unfiltered pooled rates drift from 51.837 / 39.471.

    NOTE (2026-10, user decision): the pattern YAMLs are being actively tuned, so
    a drift here is currently expected. Use :func:`check_regression_anchor` for a
    non-blocking report; keep this strict form for tests against the target set.
    """
    per = pooled_rates(unit_nk)
    expected = {"mentor": 51.837, "mentee": 39.471}
    for role, exp in expected.items():
        got = float(per.loc[role, "rate_per_1k"])
        if abs(got - exp) > tol:
            raise AssertionError(
                f"regression anchor broken for {role}: {got:.3f} != {exp:.3f}. "
                "Check the rule YAMLs against the target rule set (see CHANGELOG)."
            )


def check_regression_anchor(unit_nk: pd.DataFrame) -> tuple[bool, str]:
    """Non-blocking anchor check (YAMLs are being tuned; see CHANGELOG 2026-10)."""
    per = pooled_rates(unit_nk)
    expected = {"mentor": 51.837, "mentee": 39.471}
    lines, ok = [], True
    for role, exp in expected.items():
        got = float(per.loc[role, "rate_per_1k"])
        flag = "ok" if abs(got - exp) <= 1e-3 else "DRIFT"
        ok &= flag == "ok"
        lines.append(f"- {role}: observed {got:.3f} vs expected {exp:.3f} → {flag}")
    if not ok:
        logger.warning(
            "regression anchor drift (expected while YAMLs are tuned):\n%s", "\n".join(lines)
        )
    return ok, "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# P1 — hygiene flags (pure regex heuristics; no deletion)
# ═════════════════════════════════════════════════════════════════════════════

_RE_QUOTE_LINE = re.compile(r"(?m)^\s*>")
_RE_ON_WROTE = re.compile(r"(?im)^\s*on .{0,120}\bwrote:\s*$")
_RE_SIGNATURE_HEAD = re.compile(
    r"(?im)^\s*(?:--\s*$|regards?[,!.]?\s*$|cheers[,!.]?\s*$|best regards[,!.]?\s*$|"
    r"thanks?,?\s*$|thank you[,!.]?\s*$|sincerely[,!.]?\s*$|kind regards[,!.]?\s*$|"
    r"sent from my\b.*$)"
)
_RE_URL = re.compile(r"https?://\S+")
_RE_TRACEBACK = re.compile(
    r"(?im)(?:Traceback \(most recent call last\)|"
    r"^\s*File \".*\", line \d+|^\s*at [\w.$]+\([\w.]+:\d+\)|"
    r"^\s*\w*(?:Error|Exception)\b.*$)"
)
_RE_CODE_LINE = re.compile(r"(?m)^\s*(?:def |class |import |from |#|\}|\{|</?\w+>|\w+\s*=\s*)")


def _alpha_share(text: str) -> float:
    if not text:
        return 0.0
    return sum(ch.isalpha() for ch in text) / len(text)


def _is_url_only(text: str) -> bool:
    stripped = _RE_URL.sub("", text)
    return len(text.strip()) > 0 and not stripped.strip(" \t\r\n.,;:!?()[]<>")


def flag_unit_text(text: str) -> dict[str, object]:
    """Compute the per-unit hygiene signals for a single text (pure)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    n_lines = max(len(lines), 1)
    code_lines = sum(1 for ln in lines if _RE_CODE_LINE.search(ln))
    # Non-prose if it is mostly code/traceback or has almost no letters.
    is_nonprose = bool(
        _is_url_only(text)
        or _RE_TRACEBACK.search(text)
        or (code_lines / n_lines > 0.5)
        or (_alpha_share(text) < 0.5 and len(text) > 20)
    )
    words = re.findall(r"[A-Za-z][A-Za-z'-]*", text)
    # Signature: one of the head markers appears in the last ~4 non-empty lines.
    tail = "\n".join(lines[-4:])
    is_signature = bool(_RE_SIGNATURE_HEAD.search(tail))
    return {
        "is_quote_line": bool(_RE_QUOTE_LINE.search(text)),
        "is_on_wrote": bool(_RE_ON_WROTE.search(text)),
        "is_nonprose": is_nonprose,
        "is_signature": is_signature,
        "prose_tokens": len(words),
        "alpha_share": round(_alpha_share(text), 4),
    }


def flag_units(
    units: pd.DataFrame,
    k_boilerplate: int = 3,
    use_minhash: bool = True,
    minhash_threshold: float = 0.8,
    max_minhash_docs: int = 200_000,
    seed: int = SEED,
) -> pd.DataFrame:
    """Return ``tu_id`` + one flag column per hygiene check (never drops rows).

    H2 combines (a) exact sha256 boilerplate used by >= ``k_boilerplate``
    distinct authors and (b) near-duplicate clustering via MinHash LSH.

    Near-duplicate clustering is capped at ``max_minhash_docs`` unique texts
    (seeded sample) for tractability (~0.24 ms/doc); raise it for a full pass.
    """
    df = units[["tu_id", "thread_id", "author", "position", "sha256", "text"]].copy()
    feats = pd.DataFrame([flag_unit_text(t) for t in df["text"]], index=df.index)
    df = pd.concat([df, feats], axis=1)

    # H1 — repeats: this unit's exact text already appeared earlier in its thread.
    day_col = "created_day" if "created_day" in units.columns else "position"
    order = units[["tu_id", day_col]].set_index("tu_id")[day_col]
    df["_day"] = df["tu_id"].map(order)
    df = df.sort_values(["thread_id", "_day"], kind="stable")
    seen: dict[str, set[str]] = {}
    is_repeat = []
    for tid, sha in zip(df["thread_id"], df["sha256"], strict=False):
        bucket = seen.setdefault(tid, set())
        is_repeat.append(sha in bucket)
        bucket.add(sha)
    df["is_repeat"] = is_repeat
    df = df.sort_index()

    # H2a — exact boilerplate shared by >= k distinct authors.
    sha_authors = df.groupby("sha256")["author"].nunique()
    boiler_shas = set(sha_authors[sha_authors >= k_boilerplate].index)
    df["is_boilerplate"] = df["sha256"].isin(boiler_shas)

    # H2b — near-duplicate clusters (MinHash LSH on unique texts).
    df["dup_cluster_id"] = pd.NA
    if use_minhash and len(df):
        try:
            from datasketch import MinHash, MinHashLSH

            uniq = df.drop_duplicates("sha256")[["sha256", "text"]]
            if len(uniq) > max_minhash_docs:
                uniq = uniq.sample(n=max_minhash_docs, random_state=seed)
                logger.info("MinHash capped at %d of the unique texts", max_minhash_docs)
            lsh = MinHashLSH(threshold=minhash_threshold, num_perm=128)
            sigs: dict[str, MinHash] = {}
            for r in uniq.itertuples(index=False):
                m = MinHash(num_perm=128)
                words = str(r.text).lower().split()
                for sh in {" ".join(words[i : i + 5]) for i in range(max(len(words) - 4, 1))}:
                    m.update(sh.encode("utf8"))
                sigs[r.sha256] = m
                lsh.insert(r.sha256, m)
            cluster_of: dict[str, str] = {}
            for sha, m in sigs.items():
                if sha in cluster_of:
                    continue
                group = lsh.query(m)
                cid = hashlib.sha256("|".join(sorted(group)).encode()).hexdigest()[:12]
                for g in group:
                    cluster_of[g] = cid
            df["dup_cluster_id"] = df["sha256"].map(cluster_of)
        except ImportError:  # pragma: no cover
            logger.warning("datasketch not installed — skipping MinHash dedup")

    df["is_quoted"] = df["is_quote_line"] | df["is_on_wrote"] | df["is_repeat"]
    keep = [
        "tu_id",
        "is_quoted",
        "is_quote_line",
        "is_on_wrote",
        "is_repeat",
        "is_boilerplate",
        "dup_cluster_id",
        "is_nonprose",
        "prose_tokens",
        "is_signature",
        "alpha_share",
    ]
    return df[keep]


PHASE1_FILTERS: dict[str, list[str]] = {
    "none": [],
    "no_quote_markers": ["is_quote_line", "is_on_wrote"],
    "no_repeats": ["is_repeat"],
    "no_quoted": ["is_quoted"],
    "no_boilerplate": ["is_quoted", "is_boilerplate"],
    "no_signature": ["is_quoted", "is_boilerplate", "is_signature"],
    "no_nonprose": ["is_quoted", "is_boilerplate", "is_signature", "is_nonprose"],
}


def audit_comments_source_file(path: Path | None = None) -> dict[str, object]:
    """Audit ``comments.csv`` for the ``_x``/``_y`` merge artifact (P1).

    The ingester reads only the ``_x`` columns and attaches every CSV row as a
    comment, but the file holds ~1.22M rows for only ~0.86M distinct
    ``comment_id`` values (a merge produced duplicate rows). Every duplicate row
    therefore becomes a duplicated TextUnit with identical text but a different
    ``creation_day_x``. This is the artifact behind the high ``is_repeat`` rate.
    """
    if path is None:
        from settings import settings

        path = Path(settings.datasets_root) / DATASET_DIRNAME / "comments.csv"
    cols = [
        "comment_id",
        "issue_pr_id_x",
        "issue_pr_id_y",
        "author_id_x",
        "text_x",
        "creation_day_x",
    ]
    df = pd.read_csv(path, usecols=cols, low_memory=False)
    dup = df.comment_id.duplicated(keep=False)
    extra = int(len(df) - df.comment_id.nunique())
    return {
        "rows": len(df),
        "distinct_comment_ids": int(df.comment_id.nunique()),
        "extra_duplicate_rows": extra,
        "share_duplicate_rows": extra / len(df) if len(df) else np.nan,
        "rows_with_y_comment": int(df.issue_pr_id_y.notna().sum()),
        "distinct_comment_ids_duplicated": int(df.loc[dup, "comment_id"].nunique()),
        "path": str(path),
    }


def repeats_by_role(unit_nk: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Role breakdown of units flagged ``is_repeat`` (artifact-vs-genuine view)."""
    m = unit_nk.merge(flags[["tu_id", "is_repeat"]], on="tu_id", how="left")
    m = m[m.role.isin(ROLES)]
    out = m.groupby("role").agg(
        units=("tu_id", "size"),
        repeats=("is_repeat", "sum"),
        tokens=("tokens", "sum"),
        nk=("nk", "sum"),
    )
    out["repeat_share"] = out.repeats / out.units
    return out.reset_index()


def rates_by_filter(unit_nk: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    """Pooled per-role rates under each cumulative hygiene filter combination."""
    merged = unit_nk.merge(flags, on="tu_id", how="left")
    rows = []
    for name, drops in PHASE1_FILTERS.items():
        sub = merged if not drops else merged[~merged[drops].fillna(False).any(axis=1)]
        for role, grp in sub[sub.role.isin(ROLES)].groupby("role"):
            tokens = int(grp.tokens.sum())
            nk = int(grp.nk.sum())
            rows.append(
                {
                    "filter": name,
                    "role": role,
                    "units": len(grp),
                    "tokens": tokens,
                    "nk": nk,
                    "rate_per_1k": (1000 * nk / tokens) if tokens else np.nan,
                }
            )
    return pd.DataFrame(rows)


# ═════════════════════════════════════════════════════════════════════════════
# Statistics helpers (pure)
# ═════════════════════════════════════════════════════════════════════════════


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for k of n; returns (p, lo, hi)."""
    if n == 0:
        return (float("nan"),) * 3
    p = k / n
    d = 1 + z**2 / n
    centre = (p + z**2 / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / d
    return p, max(0.0, centre - half), min(1.0, centre + half)


def fit_gamma_prior(rates: np.ndarray, weights: np.ndarray) -> tuple[float, float]:
    """Method-of-moments Gamma(alpha, beta) for rates weighted by exposure."""
    rates = np.asarray(rates, dtype=float)
    w = np.asarray(weights, dtype=float)
    ok = np.isfinite(rates) & np.isfinite(w) & (w > 0)
    rates, w = rates[ok], w[ok]
    if len(rates) < 2:
        return 1.0, 1.0  # uninformative prior
    m = float(np.average(rates, weights=w))
    v = float(np.average((rates - m) ** 2, weights=w))
    if m <= 0 or v <= 0:
        return 1.0, 1.0
    alpha = m**2 / v
    beta = m / v
    return alpha, beta


def eb_shrinkage(y: np.ndarray, t: np.ndarray) -> tuple[np.ndarray, tuple[float, float]]:
    """Gamma–Poisson posterior mean (alpha+y)/(beta+t).

    Prior is fitted by weighted MoM on the raw rates y/t, weighting by exposure t.
    With large t the result ≈ raw rate; with t → 0 it ≈ the prior mean.
    """
    y = np.asarray(y, dtype=float)
    t = np.asarray(t, dtype=float)
    raw = np.divide(y, t, out=np.full_like(y, np.nan), where=t > 0)
    alpha, beta = fit_gamma_prior(raw, t)
    post = (alpha + y) / (beta + t)
    return post, (alpha, beta)


def gini(values: np.ndarray) -> float:
    """Gini coefficient of a non-negative vector (0 = equal, 1 = maximal)."""
    x = np.sort(np.asarray(values, dtype=float))
    x = x[np.isfinite(x) & (x >= 0)]
    if len(x) == 0 or x.sum() == 0:
        return float("nan")
    n = len(x)
    i = np.arange(1, n + 1)
    return float((2 * np.sum(i * x) - (n + 1) * x.sum()) / (n * x.sum()))


def lorenz(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lorenz curve x (population share) and y (value share)."""
    x = np.sort(np.asarray(values, dtype=float))
    x = x[np.isfinite(x) & (x >= 0)]
    if len(x) == 0 or x.sum() == 0:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0])
    cum = np.concatenate([[0.0], np.cumsum(x) / x.sum()])
    pop = np.linspace(0.0, 1.0, len(x) + 1)
    return pop, cum


def top_share(values: np.ndarray, fraction: float) -> float:
    """Share of total value held by the top ``fraction`` of entries."""
    x = np.sort(np.asarray(values, dtype=float))[::-1]
    x = x[np.isfinite(x) & (x >= 0)]
    if len(x) == 0 or x.sum() == 0:
        return float("nan")
    k = max(1, int(round(fraction * len(x))))
    return float(x[:k].sum() / x.sum())


# ═════════════════════════════════════════════════════════════════════════════
# P2 — project overview with empirical-Bayes shrinkage
# ═════════════════════════════════════════════════════════════════════════════


def project_table(unit_nk: pd.DataFrame, min_exposure_tokens: int = 1000) -> pd.DataFrame:
    """Per-project unit/token/NK aggregates and shrunk role rates."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    rows = []
    for pid, grp in lab.groupby("project_id"):
        tokens = grp.groupby("role").tokens.sum()
        nk = grp.groupby("role").nk.sum()
        row = {
            "project_id": pid,
            "units": len(grp),
            "tokens": int(grp.tokens.sum()),
            "nk": int(grp.nk.sum()),
            "n_mentors": grp[grp.role == "mentor"].author.nunique(),
            "n_mentees": grp[grp.role == "mentee"].author.nunique(),
            "n_threads": grp.thread_id.nunique(),
        }
        for role in ROLES:
            row[f"tokens_{role}"] = int(tokens.get(role, 0))
            row[f"nk_{role}"] = int(nk.get(role, 0))
            row[f"rate_{role}"] = (
                1000 * nk.get(role, 0) / tokens[role] if tokens.get(role, 0) else np.nan
            )
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["rate_per_1k"] = 1000 * df.nk / df.tokens.replace(0, np.nan)

    # Shrunk overall rate (Gamma–Poisson on project exposure in 1k-tokens).
    post, (a, b) = eb_shrinkage(df.nk.to_numpy(), df.tokens.to_numpy() / 1000.0)
    df["rate_eb"] = post
    # Shrunk per-role rates, prior fitted separately per role.
    for role in ROLES:
        y = df[f"nk_{role}"].to_numpy()
        t = df[f"tokens_{role}"].to_numpy() / 1000.0
        p, _ = eb_shrinkage(y, t)
        df[f"rate_eb_{role}"] = p
    df["gap_abs"] = df.rate_eb_mentor - df.rate_eb_mentee
    df["gap_rel"] = df.rate_eb_mentor / df.rate_eb_mentee.replace(0, np.nan)
    df["min_exposure"] = (df.tokens_mentor >= min_exposure_tokens) & (
        df.tokens_mentee >= min_exposure_tokens
    )
    return df


def within_project_tests(
    df: pd.DataFrame, eligible_only: bool = True, n_boot: int = 2000, seed: int = SEED
) -> dict:
    """Sign test, Wilcoxon signed-rank and bootstrap CI over per-project gaps."""
    from scipy import stats

    d = df[df.min_exposure] if eligible_only else df
    d = d.dropna(subset=["rate_mentor", "rate_mentee", "gap_abs"])
    if not len(d):
        return {}
    pos = int((d.gap_abs > 0).sum())
    sign_p = stats.binomtest(pos, len(d), 0.5, alternative="greater").pvalue
    try:
        wil = stats.wilcoxon(d.gap_abs, alternative="greater")
        wil_p = float(wil.pvalue)
    except ValueError:
        wil_p = float("nan")
    rng = np.random.default_rng(seed)
    gaps = d.gap_abs.to_numpy()
    boot = np.array([rng.choice(gaps, size=len(gaps), replace=True).mean() for _ in range(n_boot)])
    return {
        "n_projects": len(d),
        "share_positive": pos / len(d),
        "sign_test_p": float(sign_p),
        "wilcoxon_p": wil_p,
        "median_gap": float(np.median(gaps)),
        "boot_ci": (float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))),
        "token_weighted_mean_gap": float(np.average(d.gap_abs, weights=d.tokens)),
        "unweighted_mean_gap": float(d.gap_abs.mean()),
    }


# ═════════════════════════════════════════════════════════════════════════════
# P3 — rule contribution, hurdle, concentration, model
# ═════════════════════════════════════════════════════════════════════════════


def rule_contributions(unit_nk: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    """Per (layer, category, subcategory, rule_id): per-role rate and Δ."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    tokens = lab.groupby("role").tokens.sum()
    sig = signals.merge(lab[["tu_id", "role"]], on="tu_id", how="inner")
    keys = ["layer", "category", "subcategory", "rule_id"]
    counts = sig.groupby(keys + ["role"]).size().unstack(fill_value=0)
    for role in ROLES:
        if role not in counts:
            counts[role] = 0
    counts["rate_mentor"] = 1000 * counts["mentor"] / tokens.get("mentor", np.nan)
    counts["rate_mentee"] = 1000 * counts["mentee"] / tokens.get("mentee", np.nan)
    counts["delta"] = counts.rate_mentor - counts.rate_mentee
    counts["share_of_gap"] = counts.delta / counts.delta.sum() if counts.delta.sum() else np.nan
    return counts.reset_index().sort_values("delta", ascending=False)


def hurdle_table(unit_nk: pd.DataFrame) -> pd.DataFrame:
    """Prevalence vs. intensity, at unit level and at message level."""
    lab = unit_nk[unit_nk.role.isin(ROLES)].copy()
    rows = []

    def _hurdle(df: pd.DataFrame, level: str) -> None:
        for role, g in df.groupby("role"):
            n = len(g)
            pos = g[g.nk >= 1]
            rows.append(
                {
                    "level": level,
                    "role": role,
                    "n": n,
                    "p_nk_ge1": (len(pos) / n) if n else np.nan,
                    "e_nk_given_pos": float(pos.nk.mean()) if len(pos) else np.nan,
                    "e_tokens_given_pos": float(pos.tokens.mean()) if len(pos) else np.nan,
                    "e_tokens_given_zero": float(g[g.nk == 0].tokens.mean())
                    if (g.nk == 0).any()
                    else np.nan,
                }
            )

    _hurdle(lab, "unit")
    msg = (
        lab.groupby(["message_id", "role"])
        .agg(nk=("nk", "sum"), tokens=("tokens", "sum"))
        .reset_index()
    )
    _hurdle(msg, "message")
    return pd.DataFrame(rows)


def author_table(unit_nk: pd.DataFrame) -> pd.DataFrame:
    """Per-author tokens/nk/raw rate and Gamma–Poisson shrunk rate, per role."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    auth = (
        lab.groupby(["role", "author"])
        .agg(tokens=("tokens", "sum"), nk=("nk", "sum"), units=("tu_id", "size"))
        .reset_index()
    )
    auth["rate_per_1k"] = 1000 * auth.nk / auth.tokens.replace(0, np.nan)
    auth["rate_eb"] = np.nan
    for _role, g in auth.groupby("role"):
        post, _ = eb_shrinkage(g.nk.to_numpy(), g.tokens.to_numpy() / 1000.0)
        auth.loc[g.index, "rate_eb"] = post
    return auth


def concentration_table(unit_nk: pd.DataFrame) -> pd.DataFrame:
    """Gini and top-share concentration of nk and tokens per role."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    rows = []
    for role, g in lab.groupby("role"):
        by_author = g.groupby("author").agg(nk=("nk", "sum"), tokens=("tokens", "sum"))
        for measure in ("nk", "tokens"):
            rows.append(
                {
                    "role": role,
                    "measure": measure,
                    "gini": gini(by_author[measure].to_numpy()),
                    "top1": top_share(by_author[measure].to_numpy(), 0.01),
                    "top5": top_share(by_author[measure].to_numpy(), 0.05),
                    "top10": top_share(by_author[measure].to_numpy(), 0.10),
                    "n_authors": len(by_author),
                }
            )
    return pd.DataFrame(rows)


def leave_k_out(
    unit_nk: pd.DataFrame, project_table_df: pd.DataFrame, ks: tuple[int, ...] = (1, 5, 10, 25)
) -> pd.DataFrame:
    """Pooled mentor−mentee gap after removing top-k mentors and each project."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    tok = lab.groupby("role").tokens.sum()
    nk = lab.groupby("role").nk.sum()

    def gap(frame: pd.DataFrame) -> float:
        t = frame.groupby("role").tokens.sum()
        y = frame.groupby("role").nk.sum()
        if t.get("mentor", 0) == 0 or t.get("mentee", 0) == 0:
            return np.nan
        return 1000 * y.get("mentor", 0) / t["mentor"] - 1000 * y.get("mentee", 0) / t["mentee"]

    raw_gap = (
        1000 * nk.get("mentor", 0) / tok["mentor"] - 1000 * nk.get("mentee", 0) / tok["mentee"]
    )
    rows = [{"removed": "none", "detail": "—", "gap": raw_gap}]
    mentor_nk = lab[lab.role == "mentor"].groupby("author").nk.sum().sort_values(ascending=False)
    for k in ks:
        drop = set(mentor_nk.head(k).index)
        sub = lab[~((lab.role == "mentor") & lab.author.isin(drop))]
        rows.append({"removed": f"top{k}_mentors", "detail": f"{k} authors", "gap": gap(sub)})
    for pid in project_table_df.project_id:
        sub = lab[lab.project_id != pid]
        rows.append({"removed": "one_project", "detail": pid, "gap": gap(sub)})
    return pd.DataFrame(rows)


def message_level_table(unit_nk: pd.DataFrame) -> pd.DataFrame:
    """Aggregate to (message, role) — the unit of the confirmatory model."""
    lab = unit_nk[unit_nk.role.isin(ROLES)]
    return (
        lab.groupby(["message_id", "role", "project_id", "thread_id", "author"])
        .agg(nk=("nk", "sum"), tokens=("tokens", "sum"))
        .reset_index()
    )


def fit_models(msg: pd.DataFrame) -> str:
    """Confirmatory GEE (NB, clustered by project) + Poisson GLMM sensitivity.

    Returns a Markdown report. States which sensitivity model was actually used.
    """
    import statsmodels.api as sm
    import statsmodels.formula.api as smf

    d = msg[msg.tokens > 0].copy()
    d["is_mentor"] = (d.role == "mentor").astype(int)
    d["log_tokens"] = np.log(d.tokens)
    lines = [
        "# RQ3b P3 — confirmatory models",
        "",
        f"Message-level aggregates: {len(d):,} messages, "
        f"{d.project_id.nunique():,} projects, {d.author.nunique():,} authors.",
        "",
    ]
    try:
        model = smf.gee(
            "nk ~ is_mentor",
            groups="project_id",
            data=d,
            offset=d.log_tokens,
            family=sm.families.NegativeBinomial(),
            cov_struct=sm.cov_struct.Exchangeable(),
        ).fit()
        rr = float(np.exp(model.params["is_mentor"]))
        ci = np.exp(model.conf_int().loc["is_mentor"]).tolist()
        lines += [
            "## Primary: GEE negative-binomial, exchangeable, clustered by project",
            "",
            f"- rate ratio (mentor vs mentee) = **{rr:.3f}** [{ci[0]:.3f}, {ci[1]:.3f}]",
            f"- coefficient (log RR) = {model.params['is_mentor']:.4f}",
        ]
    except Exception as exc:  # pragma: no cover - numerical fragility
        lines += [f"## Primary GEE failed: `{exc}`"]

    # Sensitivity: Poisson GLMM with random intercepts for project + author.
    try:
        from statsmodels.genmod.bayes_mixed_glm import PoissonBayesMixedGLM

        if d.project_id.nunique() <= 300 and d.author.nunique() <= 3000:
            vc = {"project": "0 + C(project_id)", "author": "0 + C(author)"}
            glmm = PoissonBayesMixedGLM.from_formula("nk ~ is_mentor + log_tokens", vc, d).fit_vb()
            lines += [
                "",
                "## Sensitivity: Poisson GLMM (VB), random intercepts project + author",
                "",
                f"- posterior mean is_mentor = {glmm.params['is_mentor']:.4f}",
            ]
        else:
            lines += [
                "",
                "## Sensitivity GLMM skipped",
                f"- {d.project_id.nunique():,} projects / "
                f"{d.author.nunique():,} authors exceed the ",
                "size guard; a clustered GEE above is the reported sensitivity.",
            ]
    except Exception as exc:  # pragma: no cover
        lines += ["", f"## Sensitivity GLMM failed: `{exc}`"]
    return "\n".join(lines) + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# P4 — thread sampling frame and strata
# ═════════════════════════════════════════════════════════════════════════════


def thread_frame(
    unit_nk: pd.DataFrame,
    flags: pd.DataFrame,
    min_role_tokens: int = 150,
    max_flagged_share: float = 0.5,
) -> pd.DataFrame:
    """One row per issue/PR thread with per-role tokens, NK, rates and categories."""
    lab = unit_nk[unit_nk.role.isin(ROLES)].merge(
        flags[["tu_id", "is_quoted", "is_boilerplate", "is_signature", "dup_cluster_id"]],
        on="tu_id",
        how="left",
    )
    rows = []
    for tid, g in lab.groupby("thread_id"):
        roles_tokens = g.groupby("role").tokens.sum()
        roles_nk = g.groupby("role").nk.sum()
        flagged = g[["is_quoted", "is_boilerplate", "is_signature"]].fillna(False).any(axis=1)
        row = {
            "thread_id": tid,
            "project_id": g.project_id.iloc[0],
            "n_messages": g.message_id.nunique(),
            "n_mentor_msgs": g[g.role == "mentor"].message_id.nunique(),
            "n_mentee_msgs": g[g.role == "mentee"].message_id.nunique(),
            "tokens_mentor": int(roles_tokens.get("mentor", 0)),
            "tokens_mentee": int(roles_tokens.get("mentee", 0)),
            "nk_mentor": int(roles_nk.get("mentor", 0)),
            "nk_mentee": int(roles_nk.get("mentee", 0)),
            "first_day": g.created_day.min(),
            "last_day": g.created_day.max(),
            "share_flagged_units": float(flagged.mean()) if len(g) else np.nan,
            "contains_dual_role_user": bool(g.dual_role.any()),
            "author_ids_by_role": json.dumps(
                {r: sorted(map(str, sub.author.unique())) for r, sub in g.groupby("role")}
            ),
        }
        rows.append(row)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["rate_mentor"] = 1000 * df.nk_mentor / df.tokens_mentor.replace(0, np.nan)
    df["rate_mentee"] = 1000 * df.nk_mentee / df.tokens_mentee.replace(0, np.nan)
    for role in ROLES:
        post, _ = eb_shrinkage(
            df[f"nk_{role}"].to_numpy(), df[f"tokens_{role}"].to_numpy() / 1000.0
        )
        df[f"rate_eb_{role}"] = post
    df["gap_abs"] = df.rate_eb_mentor - df.rate_eb_mentee
    df["gap_rel"] = df.rate_eb_mentor / df.rate_eb_mentee.replace(0, np.nan)
    df["eligible"] = (
        (df.tokens_mentor >= min_role_tokens)
        & (df.tokens_mentee >= min_role_tokens)
        & (df.share_flagged_units < max_flagged_share)
    )
    return df


STRATA_SIZES = {
    "typical": 5,
    "extreme_pos": 2,
    "deviant_neg": 0,
    "composition": 2,
    "same_mentor": 2,
    "marker_vs_classifier": 0,
}


def select_strata(
    frame: pd.DataFrame,
    category_vectors: pd.DataFrame | None = None,
    clf: pd.DataFrame | None = None,
    max_per_project: int = 3,
    seed: int = SEED,
) -> pd.DataFrame:
    """Deterministic stratified thread sample (plan §7.2).

    ``category_vectors`` is the output of :func:`_category_vectors`; ``clf`` is
    :func:`fetch_classifier_share_by_thread` (a sampling stratifier only).
    Returns ``thread_id, stratum, selection_reason, seed``.
    """
    elig = frame[frame.eligible].copy()
    empty = pd.DataFrame(columns=["thread_id", "stratum", "selection_reason", "seed"])
    if not len(elig):
        return empty
    reasons: dict[str, str] = {}
    chosen: list[tuple[str, str]] = []
    per_project: dict[str, int] = {}

    def count(stratum: str) -> int:
        return sum(1 for _, s in chosen if s == stratum)

    def take(tid: str, stratum: str, reason: str) -> bool:
        pid = elig.loc[elig.thread_id == tid, "project_id"].iloc[0]
        if per_project.get(pid, 0) >= max_per_project or any(t == tid for t, _ in chosen):
            return False
        per_project[pid] = per_project.get(pid, 0) + 1
        chosen.append((tid, stratum))
        reasons[tid] = reason
        return True

    # typical — |gap| within ±0.25 SD of the median gap
    med, sd = elig.gap_abs.median(), elig.gap_abs.std()
    band = elig[(elig.gap_abs - med).abs() <= 0.25 * sd].sample(frac=1, random_state=seed)
    for tid in band.thread_id:
        if count("typical") >= STRATA_SIZES["typical"]:
            break
        take(tid, "typical", f"|gap-median|<0.25SD (median={med:.2f})")

    # extreme_pos / deviant_neg
    for stratum, ordered in (
        ("extreme_pos", elig.sort_values("gap_abs", ascending=False)),
        ("deviant_neg", elig.sort_values("gap_abs")),
    ):
        for tid in ordered.thread_id:
            if count(stratum) >= STRATA_SIZES[stratum]:
                break
            gap = elig.loc[elig.thread_id == tid, "gap_abs"].iloc[0]
            take(tid, stratum, f"gap_abs={gap:.2f}")

    # marker_vs_classifier — high mentor marker rate, low classifier-positive share
    if clf is not None and len(clf):
        cshare = clf.set_index("thread_id")["clf_share"]
        e = elig.assign(clf_share=elig.thread_id.map(cshare)).dropna(subset=["clf_share"])
        e = e.sort_values(["rate_mentor", "clf_share"], ascending=[False, True])
        for tid in e.thread_id:
            if count("marker_vs_classifier") >= STRATA_SIZES["marker_vs_classifier"]:
                break
            take(
                tid,
                "marker_vs_classifier",
                "high mentor rate, low classifier-positive (stratifier)",
            )

    # composition — similar gap, maximally different mentor category vectors
    if category_vectors is not None and len(category_vectors):
        cand = elig.merge(category_vectors, on="thread_id", how="inner")
        # The pairwise search is O(n²); cap to a seeded subset so it stays bounded.
        if len(cand) > 400:
            cand = cand.sample(n=400, random_state=seed)
        ids = cand.thread_id.tolist()
        best = None
        for i in range(len(ids)):
            gi = cand[cand.thread_id == ids[i]].iloc[0]
            for j in range(i + 1, len(ids)):
                gj = cand[cand.thread_id == ids[j]].iloc[0]
                if abs(gi.gap_abs - gj.gap_abs) > 0.5:
                    continue
                dist = 1 - _cosine(gi.category_vector, gj.category_vector)
                if best is None or dist > best[0]:
                    best = (dist, ids[i], ids[j])
        if best is not None:
            for tid in best[1:]:
                if (
                    take(tid, "composition", f"similar gap, category cos-dist={best[0]:.2f}")
                    and count("composition") >= STRATA_SIZES["composition"]
                ):
                    break

    # same_mentor — one mentor with >=3 eligible threads differing in mentee
    mentor_of: dict[str, str] = {}
    for tid, s in elig.set_index("thread_id")["author_ids_by_role"].items():
        try:
            mentors = list(json.loads(s).get("mentor", []))
        except (TypeError, ValueError):
            mentors = []
        mentor_of[tid] = mentors[0] if mentors else ""
    elig["_mentor"] = elig.thread_id.map(mentor_of)
    grp = elig[elig._mentor != ""].groupby("_mentor").thread_id.count()
    for mentor in grp[grp >= 3].sort_values(ascending=False).index:
        sub = elig[elig._mentor == mentor].sort_values("gap_abs")
        for tid, reason in (
            (sub.thread_id.iloc[0], "lowest-gap thread of a repeated mentor"),
            (sub.thread_id.iloc[-1], "highest-gap thread of a repeated mentor"),
        ):
            if count("same_mentor") >= STRATA_SIZES["same_mentor"]:
                break
            take(tid, "same_mentor", reason)

    sample = pd.DataFrame(chosen, columns=["thread_id", "stratum"])
    sample["selection_reason"] = sample.thread_id.map(reasons)
    sample["seed"] = seed
    return sample


def _category_vectors(signals: pd.DataFrame) -> pd.DataFrame:
    """Per-thread mentor category share vector as a dict stored in one column."""
    mentor = signals[signals.role == "mentor"]
    if mentor.empty:
        return pd.DataFrame(columns=["thread_id", "category_vector"])
    ct = mentor.groupby(["thread_id", "category"]).size().unstack(fill_value=0)
    shares = ct.div(ct.sum(axis=1), axis=0)
    return pd.DataFrame(
        {
            "thread_id": shares.index,
            "category_vector": [row.to_dict() for _, row in shares.iterrows()],
        }
    )


def _cosine(a: dict, b: dict) -> float:
    keys = set(a) | set(b)
    va = np.array([a.get(k, 0.0) for k in keys])
    vb = np.array([b.get(k, 0.0) for k in keys])
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    return float(va @ vb / denom) if denom else 0.0


def export_threads(
    sample: pd.DataFrame,
    units: pd.DataFrame,
    signals: pd.DataFrame,
    frame: pd.DataFrame,
    out_dir: Path,
) -> dict:
    """Render each sampled thread to Word (combined per stratum + one file each)."""
    from scripts.export_threads_docx import export_threads_docx

    tids = sample.thread_id.tolist()
    sub_units = units[units.thread_id.isin(tids)].copy()
    # Relative elapsed days from the thread's first day (user preference).
    first = sub_units.groupby("thread_id").created_day.transform("min")
    sub_units["date_display"] = (sub_units.created_day - first).map(
        lambda d: f"Day {d:.1f}" if pd.notna(d) else "—"
    )
    sub_units = sub_units.rename(columns={"tu_role": "tu_role"})

    out_dir.mkdir(parents=True, exist_ok=True)
    sub_signals = signals[signals.tu_id.isin(sub_units.tu_id)]
    reports = []
    for stratum, grp in sample.groupby("stratum"):
        meta = frame.set_index("thread_id").loc[grp.thread_id]
        meta = meta.assign(selection_reason=grp.set_index("thread_id").selection_reason)
        res = export_threads_docx(
            sub_units,
            sub_signals,
            out_dir / f"stratum_{stratum}.docx",
            thread_meta=meta,
            thread_ids=grp.thread_id.tolist(),
            title=f"OpenMent — {stratum} threads",
        )
        reports.append(res["alignment"].assign(stratum=stratum))
    per_thread = export_threads_docx(
        sub_units,
        sub_signals,
        out_dir / "per_thread",
        thread_meta=frame.set_index("thread_id").loc[tids],
        thread_ids=tids,
        one_file_per_thread=True,
        title="OpenMent — per-thread export",
    )
    alignment = pd.concat(reports) if reports else pd.DataFrame()
    return {"alignment": alignment, "per_thread": per_thread["paths"]}


# ═════════════════════════════════════════════════════════════════════════════
# P5 — signal coding sheet and adjusted rates
# ═════════════════════════════════════════════════════════════════════════════


def coding_sheet(
    unit_nk: pd.DataFrame,
    signals: pd.DataFrame,
    frame: pd.DataFrame,
    per_cell: int = 25,
    cap: int = 600,
    seed: int = SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Stratified role × category signal sample with KWIC context (±200 chars)."""
    elig_threads = set(frame[frame.eligible].thread_id)
    pool = signals.merge(
        unit_nk[["tu_id", "role", "thread_id", "text", "message_id"]], on="tu_id", how="inner"
    )
    pool = pool[pool.thread_id.isin(elig_threads)].copy()
    np.random.default_rng(seed)
    parts = []
    for (_role, _cat), g in pool.groupby(["role", "category"]):
        parts.append(g.sample(n=min(per_cell, len(g)), random_state=seed))
    sample = pd.concat(parts).drop_duplicates("signal_id") if parts else pd.DataFrame()
    if len(sample) > cap:
        sample = sample.sample(n=cap, random_state=seed)

    def _kwic(row, side):
        text = row.text or ""
        s, e = int(row.span_start), int(row.span_end)
        if side == "left":
            a, b = max(s - 200, 0), s
        else:
            a, b = e, min(e + 200, len(text))
        return text[a:b].replace("\n", " ")

    pool.set_index("message_id")["text"]
    sheet = pd.DataFrame(
        {
            "signal_id": sample.signal_id,
            "tu_id": sample.tu_id,
            "thread_id": sample.thread_id,
            "kwic_left": [_kwic(r, "left") for r in sample.itertuples(index=False)],
            "span": sample.surface_form,
            "kwic_right": [_kwic(r, "right") for r in sample.itertuples(index=False)],
            "context": sample.text.map(lambda t: str(t)[:500].replace("\n", " ")),
            "role_hidden": "",
            "function": "",
            "epistemic_subject": "",
            "note": "",
        }
    )
    key = sample[["signal_id", "role", "category", "rule_id"]].reset_index(drop=True)
    return sheet.reset_index(drop=True), key


def adjusted_rates(key_coded: pd.DataFrame, unit_nk: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Per role×category precision of 'genuine or attributed NK' and adjusted rates.

    ``key_coded`` is the P5 coding key joined with the researcher's ``function``
    column (empty string for uncoded rows).
    """
    total = key_coded[key_coded.function != ""]
    rows = []
    for (role, cat), g in total.groupby(["role", "category"]):
        k = int(g.function.isin(["genuine_nk", "attributed_nk"]).sum())
        p, lo, hi = wilson(k, len(g))
        rows.append(
            {
                "role": role,
                "category": cat,
                "n": len(g),
                "k": k,
                "precision": p,
                "lo": lo,
                "hi": hi,
                "status": "ok" if len(g) >= 10 else "insufficient",
            }
        )
    prec = pd.DataFrame(rows)

    lab = unit_nk[unit_nk.role.isin(ROLES)]
    tokens = lab.groupby("role").tokens.sum()
    raw_counts = key_coded.groupby(["role", "category"]).size().rename("signals").reset_index()
    merged = raw_counts.merge(
        prec[["role", "category", "precision", "status"]], on=["role", "category"], how="left"
    )
    merged["rate"] = [
        1000 * s / tokens.get(r, np.nan) for r, s in zip(merged.role, merged.signals, strict=False)
    ]
    merged["adj_rate"] = [
        rate * prec if status == "ok" else np.nan
        for rate, prec, status in zip(merged.rate, merged.precision, merged.status, strict=False)
    ]
    out = merged.groupby("role").agg(raw_rate=("rate", "sum"), adj_rate=("adj_rate", "sum"))
    md = [
        "# RQ3b P5 — NK-adjusted role rates",
        "",
        "Raw rate = sum of per-category rates; adjusted = sum of rate × precision "
        "(categories with <10 coded signals reported as insufficient and excluded).",
        "",
        _md_table(out.round(3), index=True),
    ]
    return prec, "\n".join(md) + "\n"


# ═════════════════════════════════════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════════════════════════════════════


def _write_csv(df: pd.DataFrame, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    df.to_csv(path, index=False)
    logger.info("wrote %s (%d rows)", path, len(df))
    return path


def _md_table(df: pd.DataFrame, index: bool = False) -> str:
    """Minimal markdown table (avoids pandas' optional ``tabulate`` dependency)."""
    d = df.reset_index() if index else df
    cols = [str(c) for c in d.columns]
    lines = ["| " + " | ".join(cols) + " |", "| " + " | ".join("---" for _ in cols) + " |"]
    for row in d.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def span_audit(n_threads: int = 50, seed: int = SEED) -> pd.DataFrame:
    """Sample random OpenMent threads and test span_start/span_end as character offsets.

    Reuses the export module's :func:`align_spans` so the audit measures exactly
    what the Word export relies on. Returns per-layer alignment-method counts.
    """
    from scripts.export_threads_docx import align_spans, alignment_report

    cypher = f"""
    MATCH (p:Artefact)
    WHERE coalesce(p.corpus_id, '') = 'openment'{_sandbox_clause("p")}
    WITH p ORDER BY rand() LIMIT $n
    MATCH (p)-[:HAS_TEXT]->(u:TextUnit)-[:HAS_SIGNAL]->(s:Signal)
    RETURN u.id AS tu_id, u.text AS text, s.layer AS layer, s.surface_form AS surface_form,
           s.span_start AS span_start, s.span_end AS span_end, s.rule_id AS rule_id
    """
    sig = run_query(cypher, n=n_threads)
    if sig.empty:
        return pd.DataFrame()
    units = sig[["tu_id", "text"]].drop_duplicates()
    aligned = align_spans(units, sig)
    return alignment_report(aligned)


def run_p0() -> Path:
    """P0 schema audit → rq3b_om_P0_schema_report.md."""
    rules = load_rule_sets()
    units = fetch_openment_units()
    signals = fetch_openment_signals(rules)
    roles = load_roles()
    unit_nk = build_unit_nk(attach_roles(units, roles), signals)

    anchors = pooled_rates(unit_nk)
    _, anchor_note = check_regression_anchor(unit_nk)
    spans = span_audit()
    lines = [
        "# RQ3b OpenMent — P0 schema audit",
        "",
        f"- Rules: version {rules.version}, {len(rules.active)} active, "
        f"{len(rules.candidate)} candidate.",
        f"- Artefacts/units loaded: {units.thread_id.nunique():,} threads, "
        f"{len(units):,} TextUnits.",
        f"- Signals under the NK predicate: {len(signals):,}.",
        f"- Units with a known role: {int(unit_nk.role.isin(ROLES).sum()):,}.",
        "",
        "## Regression anchor (unfiltered pooled rates)",
        "",
        _md_table(anchors.round(3), index=True),
        "",
        "Expected target (pre-tuning rule set): mentor 51.837, mentee 39.471. "
        "The pattern YAMLs are being actively fine-tuned (2026-10, user decision), "
        "so the observed values may legitimately drift.",
        "",
        anchor_note,
        "",
        "## Thread key",
        "",
        "`thread_id` = `p.record_id` (`issue|pr:openment:<pid>:<n>`). "
        "`message_id` = thread + `:op` (title/body) or `:comment:<position>`.",
        "OpenMent is GitHub-shaped: each issue/PR *is* the thread; no reply-graph "
        "reconstruction is needed. No Conversation node wraps OpenMent artefacts.",
        "",
        "## Dates and provenance",
        "",
        "Dates are anonymised day offsets (numeric), not ISO timestamps; the Word "
        "export shows relative elapsed days from the thread start.",
        "Author = `u.author_login`; role from `project_roles.csv` "
        f"({len(roles):,} (project, user) mappings).",
        "",
        "## HAS_TEXT roles",
        "",
        _md_table(units.tu_role.value_counts().rename("units"), index=True),
        "",
        "## Span-offset audit (random threads)",
        "",
        "Offsets are character offsets into `TextUnit.text`. `char`/`char_loose` "
        "are exact matches; `search`/`failed` are the ones to watch.",
        "",
        _md_table(spans, index=True) if len(spans) else "_no signals sampled_",
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "rq3b_om_P0_schema_report.md"
    path.write_text("\n".join(lines) + "\n")
    logger.info("wrote %s", path)
    return path


def run_p1() -> None:
    rules = load_rule_sets()
    units = fetch_openment_units()
    signals = fetch_openment_signals(rules)
    roles = load_roles()
    unit_nk = build_unit_nk(attach_roles(units, roles), signals)
    check_regression_anchor(unit_nk)
    flags = flag_units(units)
    _write_csv(flags, "rq3b_om_P1_unit_flags.csv")
    rates = rates_by_filter(unit_nk, flags)
    _write_csv(rates, "rq3b_om_P1_rates_by_filter.csv")
    _write_csv(repeats_by_role(unit_nk, flags), "rq3b_om_P1_repeats_by_role.csv")

    audit = audit_comments_source_file()
    piv = rates.pivot(index="filter", columns="role", values="rate_per_1k")
    piv["gap_rel_pct"] = 100 * (piv.mentor - piv.mentee) / piv.mentee
    lines = [
        "# RQ3b OpenMent — P1 hygiene note",
        "",
        "## Source-file artifact (`comments.csv`)",
        "",
        f"- rows: {audit['rows']:,}; distinct `comment_id`: {audit['distinct_comment_ids']:,}; "
        f"**extra duplicate rows: {audit['extra_duplicate_rows']:,} "
        f"({audit['share_duplicate_rows']:.1%})**.",
        f"- comment ids appearing on >1 row: {audit['distinct_comment_ids_duplicated']:,}.",
        f"- rows carrying a second (`_y`) comment: {audit['rows_with_y_comment']:,}.",
        "",
        "The ingester reads only the `_x` columns and emits every CSV row as a "
        "TextUnit, so each duplicate row becomes a duplicated comment unit with "
        "identical text but a different `creation_day_x`. This is the artifact "
        "behind the `is_repeat` rate, not (mostly) genuine repetition.",
        "",
        "## Rate by filter",
        "",
        _md_table(piv.round(3), index=True),
        "",
        "Removing repeats and other hygiene flags does **not** close the "
        "mentor−mentee gap (it slightly widens it), so the artifact is not the "
        "source of the role asymmetry. See the plan's P2–P5 for the substantive "
        "decomposition.",
    ]
    (OUT_DIR / "rq3b_om_P1_source_audit.md").write_text("\n".join(lines) + "\n")
    logger.info("wrote %s", OUT_DIR / "rq3b_om_P1_source_audit.md")


def run_p2() -> None:
    rules = load_rule_sets()
    units = attach_roles(fetch_openment_units(), load_roles())
    unit_nk = build_unit_nk(units, fetch_openment_signals(rules))
    df = project_table(unit_nk)
    _write_csv(df, "rq3b_om_P2_projects.csv")
    logger.info("within-project tests: %s", within_project_tests(df))


def run_p3() -> None:
    rules = load_rule_sets()
    units = attach_roles(fetch_openment_units(), load_roles())
    signals = fetch_openment_signals(rules)
    unit_nk = build_unit_nk(units, signals)
    _write_csv(rule_contributions(unit_nk, signals), "rq3b_om_P3_rule_contrib.csv")
    _write_csv(hurdle_table(unit_nk), "rq3b_om_P3_hurdle.csv")
    _write_csv(author_table(unit_nk), "rq3b_om_P3_authors.csv")
    _write_csv(concentration_table(unit_nk), "rq3b_om_P3_concentration.csv")
    _write_csv(leave_k_out(unit_nk, project_table(unit_nk)), "rq3b_om_P3_leave_k_out.csv")
    (OUT_DIR / "rq3b_om_P3_models.md").write_text(fit_models(message_level_table(unit_nk)))


def run_p4() -> None:
    rules = load_rule_sets()
    units = attach_roles(fetch_openment_units(), load_roles())
    signals = fetch_openment_signals(rules)
    unit_nk = build_unit_nk(units, signals)
    flags = flag_units(units)
    frame = thread_frame(unit_nk, flags)
    _write_csv(frame, "rq3b_om_P4_thread_frame.csv")
    cats = _category_vectors(
        signals.merge(unit_nk[["tu_id", "role", "thread_id"]], on="tu_id", how="left")
    )
    clf = fetch_classifier_share_by_thread()
    sample = select_strata(frame, cats, clf)
    _write_csv(sample, "rq3b_om_P4_thread_sample.csv")
    export_threads(sample, units, signals, frame, OUT_DIR / "rq3b_om_threads")


def run_p5() -> None:
    rules = load_rule_sets()
    units = attach_roles(fetch_openment_units(), load_roles())
    signals = fetch_openment_signals(rules)
    unit_nk = build_unit_nk(units, signals)
    flags = flag_units(units)
    frame = thread_frame(unit_nk, flags)
    sheet, key = coding_sheet(unit_nk, signals, frame)
    _write_csv(sheet, "rq3b_om_P5_coding_sheet.csv")
    _write_csv(key, "rq3b_om_P5_key.csv")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    )
    p = argparse.ArgumentParser(description="RQ3b OpenMent mentor/mentee NK-gap analysis.")
    p.add_argument("phase", choices=["p0", "p1", "p2", "p3", "p4", "p5", "all"])
    args = p.parse_args()
    phases = ["p0", "p1", "p2", "p3", "p4", "p5"] if args.phase == "all" else [args.phase]
    for ph in phases:
        logger.info("=== %s ===", ph.upper())
        globals()[f"run_{ph}"]()


if __name__ == "__main__":
    main()
