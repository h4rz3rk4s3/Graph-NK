"""tests/test_openment_roles.py — DB-free tests for scripts/openment_roles.py.

Covers the pure statistical and heuristic helpers introduced for the RQ3b
OpenMent mentor/mentee investigation. No Neo4j, no Mongo, no Redis.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from scripts.openment_roles import (
    adjusted_rates,
    coding_sheet,
    eb_shrinkage,
    fit_models,
    flag_unit_text,
    flag_units,
    gini,
    hurdle_table,
    leave_k_out,
    lorenz,
    message_level_table,
    project_table,
    rule_contributions,
    select_strata,
    thread_frame,
    top_share,
    wilson,
)

# ── statistics ───────────────────────────────────────────────────────────────


def test_gini_known_vectors():
    assert gini([5, 5, 5, 5]) == pytest.approx(0.0)
    assert gini([0, 0, 0, 10]) == pytest.approx(0.75)
    # uniform distribution has zero Gini; one holder of everything is (n-1)/n.
    assert gini([1, 1, 1]) == pytest.approx(0.0)


def test_lorenz_endpoints_and_monotonic():
    x, y = lorenz([1, 1, 1, 1])
    assert x[0] == 0.0 and y[0] == 0.0 and x[-1] == 1.0 and y[-1] == 1.0
    assert np.all(np.diff(y) >= -1e-12)


def test_top_share():
    vals = np.array([9, 1, 1, 1, 1, 1, 1, 1, 1, 1])  # top 10% holds 9/18
    assert top_share(vals, 0.10) == pytest.approx(9 / 18)


def test_eb_shrinkage_limits():
    # A dominant-exposure point is barely shrunk: posterior ≈ raw rate.
    y = np.array([10.0, 20.0, 30.0, 1000.0])
    t = np.array([10.0, 10.0, 10.0, 1e9])
    post, _ = eb_shrinkage(y, t)
    assert post[3] == pytest.approx(1000.0 / 1e9, rel=1e-3)
    # A tiny-exposure, zero-count point is pulled to the prior mean.
    y2 = np.array([10.0, 20.0, 30.0, 0.0])
    t2 = np.array([10.0, 10.0, 10.0, 0.001])
    post2, (alpha, beta) = eb_shrinkage(y2, t2)
    prior_mean = alpha / beta
    assert post2[3] == pytest.approx(alpha / (beta + t2[3]))
    assert abs(post2[3] - prior_mean) < abs(0.0 - prior_mean)


def test_wilson_bounds():
    p, lo, hi = wilson(0, 0)
    assert np.isnan(p)
    p, lo, hi = wilson(5, 10)
    assert lo < p < hi and 0 <= lo and hi <= 1


# ── hygiene heuristics ───────────────────────────────────────────────────────


def test_flag_unit_text_quote_and_signature():
    q = flag_unit_text("> old text\nOn Mon, Bob wrote:\nnew")
    assert q["is_quote_line"] and q["is_on_wrote"]
    s = flag_unit_text("Sounds good.\nThanks,\nBob")
    assert s["is_signature"]
    n = flag_unit_text('Traceback (most recent call last):\n  File "x.py", line 3')
    assert n["is_nonprose"]


def test_flag_units_exact_boilerplate_and_repeat():
    units = pd.DataFrame(
        [
            dict(
                tu_id="a",
                thread_id="T",
                author="u1",
                position=0,
                created_day=0.0,
                sha256="s1",
                text="hello world foo",
            ),
            dict(
                tu_id="b",
                thread_id="T",
                author="u2",
                position=1,
                created_day=1.0,
                sha256="s1",
                text="hello world foo",
            ),  # exact repeat in-thread
            dict(
                tu_id="c",
                thread_id="T2",
                author="u3",
                position=0,
                created_day=0.0,
                sha256="s1",
                text="hello world foo",
            ),  # boilerplate across authors
            dict(
                tu_id="d",
                thread_id="T2",
                author="u4",
                position=1,
                created_day=1.0,
                sha256="s4",
                text="a unique sentence about widgets",
            ),
        ]
    )
    flags = flag_units(units, k_boilerplate=3, use_minhash=False)
    by = flags.set_index("tu_id")
    assert bool(by.loc["b", "is_repeat"])
    assert not bool(by.loc["a", "is_repeat"])
    assert bool(by.loc["c", "is_boilerplate"])
    assert not bool(by.loc["d", "is_boilerplate"])


# ── gap decomposition ────────────────────────────────────────────────────────


def test_rule_contribution_sums_to_gap():
    unit_nk = pd.DataFrame(
        [
            dict(tu_id="m1", role="mentor", tokens=100, nk=3),
            dict(tu_id="e1", role="mentee", tokens=100, nk=1),
        ]
    )
    signals = pd.DataFrame(
        [
            dict(
                tu_id="m1",
                layer="lexical",
                category="prototype",
                subcategory="epistemic_state",
                rule_id="lex.uncertain",
            ),
            dict(
                tu_id="m1",
                layer="lexical",
                category="prototype",
                subcategory="epistemic_state",
                rule_id="lex.uncertain",
            ),
            dict(
                tu_id="m1",
                layer="morpho_syntactic",
                category="hedging",
                subcategory="adverbial",
                rule_id="morph.hedge",
            ),
            dict(
                tu_id="e1",
                layer="lexical",
                category="prototype",
                subcategory="epistemic_state",
                rule_id="lex.uncertain",
            ),
        ]
    )
    contrib = rule_contributions(unit_nk, signals)
    total_gap = 1000 * (3 / 100 - 1 / 100)
    assert contrib.delta.sum() == pytest.approx(total_gap)
    assert contrib.share_of_gap.sum() == pytest.approx(1.0)


# ── P4 strata selection ──────────────────────────────────────────────────────


def _synthetic_frame(n=60):
    rng = np.random.default_rng(0)
    rows = []
    for i in range(n):
        rows.append(
            dict(
                thread_id=f"t{i}",
                project_id=f"p{i // 3}",
                eligible=True,
                gap_abs=float(rng.normal(5, 2)),
                rate_mentor=float(rng.normal(50, 10)),
                rate_mentee=float(rng.normal(45, 10)),
                author_ids_by_role=json.dumps({"mentor": [f"m{i % 8}"], "mentee": [f"x{i}"]}),
            )
        )
    return pd.DataFrame(rows)


def test_select_strata_deterministic_and_bounded():
    frame = _synthetic_frame()
    a = select_strata(frame, category_vectors=None, clf=None, seed=7)
    b = select_strata(frame, category_vectors=None, clf=None, seed=7)
    pd.testing.assert_frame_equal(a, b)
    assert set(a.stratum) <= {
        "typical",
        "extreme_pos",
        "deviant_neg",
        "composition",
        "same_mentor",
        "marker_vs_classifier",
    }
    # no project contributes more than the cap
    per_proj = frame[frame.thread_id.isin(a.thread_id)].project_id.value_counts()
    assert per_proj.max() <= 3


# ── adjusted rates ───────────────────────────────────────────────────────────


def test_adjusted_rates_marks_insufficient():
    key = pd.DataFrame(
        [
            dict(
                signal_id="s1",
                role="mentor",
                category="hedging",
                rule_id="r",
                function="genuine_nk",
            ),
            dict(signal_id="s2", role="mentor", category="hedging", rule_id="r", function="not_nk"),
            dict(
                signal_id="s3",
                role="mentee",
                category="modality",
                rule_id="r2",
                function="genuine_nk",
            ),
        ]
    )
    unit_nk = pd.DataFrame(
        [
            dict(tu_id="u1", role="mentor", tokens=1000, nk=1),
            dict(tu_id="u2", role="mentee", tokens=1000, nk=1),
        ]
    )
    prec, _ = adjusted_rates(key, unit_nk)
    assert (prec.status == "insufficient").all()  # <10 coded per cell
    assert prec[prec.role == "mentor"].precision.iloc[0] == pytest.approx(0.5)


# ── P2 / P3 / P4 pipelines on synthetic data ─────────────────────────────────


def _unit_nk(n_threads=8, msgs_per_thread=6):
    rng = np.random.default_rng(1)
    rows = []
    for t in range(n_threads):
        for m in range(msgs_per_thread):
            role = "mentor" if m % 2 == 0 else "mentee"
            rows.append(
                dict(
                    tu_id=f"u{t}_{m}",
                    thread_id=f"th{t}",
                    project_id=f"p{t % 3}",
                    message_id=f"th{t}:m{m}",
                    author=f"{role}_{t}_{m % 2}",
                    role=role,
                    tokens=int(rng.integers(20, 120)),
                    nk=int(rng.integers(0, 4)),
                    created_day=float(m),
                    position=m,
                    sha256=f"sha{t}_{m}",
                    dual_role=False,
                    text="maybe I think we could try",
                )
            )
    return pd.DataFrame(rows)


def test_project_table_and_within_tests():
    df = project_table(_unit_nk())
    assert {"rate_eb", "gap_abs", "min_exposure"}.issubset(df.columns)
    assert df.gap_abs.notna().all()


def test_hurdle_and_message_level():
    u = _unit_nk()
    h = hurdle_table(u)
    assert set(h.level) == {"unit", "message"}
    assert (h.p_nk_ge1.between(0, 1)).all()
    msg = message_level_table(u)
    assert {"nk", "tokens", "role", "project_id"}.issubset(msg.columns)


def test_leave_k_out_returns_baseline_and_jackknife():
    u = _unit_nk()
    out = leave_k_out(u, project_table(u), ks=(1, 2))
    assert out.iloc[0].removed == "none"
    assert "top1_mentors" in set(out.removed)
    assert "one_project" in set(out.removed)


def test_fit_models_returns_markdown():
    msg = message_level_table(_unit_nk(n_threads=12, msgs_per_thread=8))
    report = fit_models(msg)
    assert "rate ratio" in report or "failed" in report


def test_thread_frame_and_coding_sheet():
    u = _unit_nk(n_threads=10)
    flags = flag_units(u, use_minhash=False)
    frame = thread_frame(u, flags, min_role_tokens=1, max_flagged_share=1.0)
    assert {"gap_abs", "eligible", "project_id"}.issubset(frame.columns)
    signals = pd.DataFrame(
        [
            dict(
                tu_id="u0_0",
                signal_id="s1",
                layer="lexical",
                category="prototype",
                subcategory="epistemic_state",
                rule_id="lex.uncertain",
                status="active",
                span_start=0,
                span_end=5,
                surface_form="maybe",
            ),
            dict(
                tu_id="u0_1",
                signal_id="s2",
                layer="hedging",
                category="hedging",
                subcategory="adverbial",
                rule_id="morph.hedge",
                status="active",
                span_start=0,
                span_end=5,
                surface_form="maybe",
            ),
        ]
    )
    sheet, key = coding_sheet(u, signals, frame, per_cell=10, cap=100)
    assert {"kwic_left", "span", "function"}.issubset(sheet.columns)
    assert set(key.columns) == {"signal_id", "role", "category", "rule_id"}
    assert len(sheet) <= 100
