"""tests/test_genre_composition.py — DB-free tests for the composition extraction.

Covers the pure helpers in ``scripts/genre_composition.py``: the 02b-compatible
genre mapping, rule→subcategory collapsing, distinct-unit join, layer-scoped
shares, and the distinctiveness flags. No Neo4j, no Mongo, no Redis.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from scripts.genre_composition import (
    GENRES,
    RULE_COLUMNS,
    SUB_COLUMNS,
    attach_subcategory_units,
    composition_shares,
    corpora_by_genre,
    distinctiveness,
    genre_of,
    in_scope_corpora,
    rule_rows_to_subcategory,
    tag_corpus,
)

# ── genre registry ───────────────────────────────────────────────────────────


def test_genre_of_uses_02b_names_and_aliases_review_email():
    assert genre_of("curated-email-code-reviews") == "email"
    assert genre_of("openment") == "tracker"
    assert genre_of("sotorrent") == "qa"
    assert genre_of("disco") == "chat"
    assert genre_of("not-a-corpus") == "EXCLUDED"


def test_in_scope_corpora_is_the_eleven_dataset_scope():
    corpora = in_scope_corpora()
    assert len(corpora) == 11
    assert "curated-email-code-reviews" in corpora
    assert corpora == sorted(corpora)


def test_corpora_by_genre_counts_and_membership():
    by_genre = corpora_by_genre()
    assert set(by_genre) == set(GENRES)
    assert len(by_genre["chat"]) == 5
    assert len(by_genre["tracker"]) == 4
    assert by_genre["qa"] == ["sotorrent"]
    assert by_genre["email"] == ["curated-email-code-reviews"]
    assert "openment" in by_genre["tracker"]
    assert all(by_genre[g] == sorted(by_genre[g]) for g in GENRES)


# ── rule → subcategory collapsing ─────────────────────────────────────────────


def _rule_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "dataset": ["disco"] * 3,
            "genre": ["chat"] * 3,
            "layer": ["lexical", "lexical", "morpho_syntactic"],
            "subcategory": ["not_knowing", "not_knowing", "not_knowing"],
            "rule_id": ["lex.unsure", "lex.idk", "morph.epi.neg_cognition"],
            "granularity": ["rule"] * 3,
            "n_signals": [10, 5, 7],
            "n_units": [pd.NA, pd.NA, pd.NA],
        }
    )


def test_tag_corpus_stamps_dataset_genre_and_granularity():
    raw = pd.DataFrame(
        {
            "layer": ["lexical"],
            "subcategory": ["not_knowing"],
            "rule_id": ["lex.idk"],
            "n_signals": [3],
        }
    )
    out = tag_corpus(raw, "disco")
    assert out.loc[0, "dataset"] == "disco"
    assert out.loc[0, "genre"] == "chat"
    assert out.loc[0, "granularity"] == "rule"
    assert pd.isna(out.loc[0, "n_units"])
    assert list(out.columns) == list(RULE_COLUMNS)


def test_rule_rows_to_subcategory_sums_hits_and_is_layer_scoped():
    out = rule_rows_to_subcategory(_rule_df())
    keyed = out.set_index(["layer", "subcategory"])["n_signals"].to_dict()
    # Two lexical rules collapse to one row (10+5); morpho not_knowing stays
    # separate despite the shared name — keys are layer-scoped.
    assert keyed[("lexical", "not_knowing")] == 15
    assert keyed[("morpho_syntactic", "not_knowing")] == 7
    assert len(out) == 2
    assert set(out["granularity"]) == {"subcategory"}
    assert out["n_units"].isna().all()


def test_rule_rows_to_subcategory_empty_keeps_columns():
    out = rule_rows_to_subcategory(pd.DataFrame(columns=list(RULE_COLUMNS)))
    assert list(out.columns) == list(SUB_COLUMNS)
    assert out.empty


def test_attach_subcategory_units_joins_distinct_counts():
    sub = rule_rows_to_subcategory(_rule_df())
    units = pd.DataFrame(
        {
            "dataset": ["disco", "disco"],
            "layer": ["lexical", "morpho_syntactic"],
            "subcategory": ["not_knowing", "not_knowing"],
            "n_units": [12, 6],  # < sum of rule units for lexical (overlap)
        }
    )
    out = attach_subcategory_units(sub, units)
    keyed = out.set_index(["layer", "subcategory"])["n_units"].to_dict()
    assert keyed[("lexical", "not_knowing")] == 12
    assert keyed[("morpho_syntactic", "not_knowing")] == 6


# ── shares ────────────────────────────────────────────────────────────────────


def _comp_frame() -> pd.DataFrame:
    # Two datasets in chat, one in qa; one layer.
    rows = [
        ("d1", "chat", "lexical", "not_knowing", 80),
        ("d1", "chat", "lexical", "epistemic_state", 20),
        ("d2", "chat", "lexical", "not_knowing", 70),
        ("d2", "chat", "lexical", "epistemic_state", 30),
        ("d3", "qa", "lexical", "not_knowing", 20),
        ("d3", "qa", "lexical", "epistemic_state", 80),
    ]
    return pd.DataFrame(
        rows, columns=["dataset", "genre", "layer", "subcategory", "n_signals"]
    ).assign(granularity="subcategory", rule_id="", n_units=pd.NA)


def test_composition_shares_sum_to_one_per_dataset_layer():
    c, P, R = composition_shares(_comp_frame())
    sums = c.groupby(["dataset", "layer"])["p"].sum()
    assert np.allclose(sums.to_numpy(), 1.0)
    assert (c["N"] == c.groupby(["dataset", "layer"])["n_signals"].transform("sum")).all()


def test_genre_and_reference_are_equal_weight():
    c, P, R = composition_shares(_comp_frame())
    # chat P[not_knowing] = mean(80/100, 70/100) = 0.75
    chat_nk = P[(P.genre == "chat") & (P.subcategory == "not_knowing")].P.iloc[0]
    assert chat_nk == pytest.approx(0.75)
    # R[not_knowing] = mean(P[chat], P[qa]) = mean(0.75, 0.20) = 0.475
    r_nk = R[R.subcategory == "not_knowing"].R.iloc[0]
    assert r_nk == pytest.approx(0.475)


# ── distinctiveness flags ─────────────────────────────────────────────────────


def test_distinctiveness_marks_a_consistent_multi_dataset_driver():
    c, _P, R = composition_shares(_comp_frame())
    ds, ge = distinctiveness(c, R, alpha=10.0, min_count=1, consistency=np.log2(1.5))
    chat = ge[(ge.genre == "chat") & (ge.subcategory == "not_knowing")].iloc[0]
    assert chat["E"] > np.log2(1.5)
    assert bool(chat["consistent_driver"]) is True  # both chat datasets over-represent
    assert bool(chat["single_dataset"]) is False
    # qa is a single-dataset genre: consistency undefined, never "consistent".
    qa = ge[(ge.genre == "qa") & (ge.subcategory == "not_knowing")].iloc[0]
    assert bool(qa["single_dataset"]) is True
    assert bool(qa["consistent_driver"]) is False


def test_distinctiveness_low_count_blocks_consistency():
    c, _P, R = composition_shares(_comp_frame())
    # min_count above the chat not_knowing counts → every cell low → no driver.
    _ds, ge = distinctiveness(c, R, alpha=10.0, min_count=10_000, consistency=np.log2(1.5))
    chat = ge[(ge.genre == "chat") & (ge.subcategory == "not_knowing")].iloc[0]
    assert bool(chat["consistent_driver"]) is False


def test_distinctiveness_dataset_effect_sign_tracks_over_representation():
    c, _P, R = composition_shares(_comp_frame())
    ds, _ge = distinctiveness(c, R, alpha=10.0, min_count=1)
    d1_nk = ds[(ds.dataset == "d1") & (ds.subcategory == "not_knowing")].iloc[0]
    d3_nk = ds[(ds.dataset == "d3") & (ds.subcategory == "not_knowing")].iloc[0]
    assert d1_nk["e"] > 0  # over-represented vs reference
    assert d3_nk["e"] < 0  # under-represented
    assert bool(d1_nk["low_count"]) is False
