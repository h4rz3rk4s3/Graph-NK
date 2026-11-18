"""tests/test_sample_units_by_genre.py — DB-free tests for the genre sampler.

Covers the pure helpers in scripts/sample_units_by_genre.py: the sha256-prefix
draw, prefix-length choice, seeded selection, source-document reconstruction,
and Mongo source routing. No Neo4j, no Mongo, no Redis.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.corpus_census import GENRE_BY_CORPUS, GENRES, corpora_by_genre, genre_of
from scripts.sample_units_by_genre import (
    build_source_text,
    choose_prefix_length,
    excel_safe,
    hex_prefix,
    layer_counts,
    select_sample,
    source_lookup,
    write_workbook,
)

# ── genre registry ───────────────────────────────────────────────────────────


def test_genre_registry_covers_scope_and_openment_is_tracker():
    assert genre_of("openment") == "tracker"
    assert genre_of("curated-email-code-reviews") == "review_email"
    assert genre_of("sotorrent") == "qa"
    assert genre_of("not-a-corpus") == "EXCLUDED"
    assert set(GENRE_BY_CORPUS.values()) <= set(GENRES)


def test_corpora_by_genre_groups_and_sorts():
    by_genre = corpora_by_genre()
    assert by_genre["qa"] == ["sotorrent"]
    assert by_genre["tracker"] == ["alternative-jira", "apache-jira", "numfocus", "openment"]
    assert "kummerfeld-irc" in by_genre["chat"]
    assert all(by_genre[g] == sorted(by_genre[g]) for g in GENRES)


# ── sha256-prefix draw ────────────────────────────────────────────────────────


def test_hex_prefix_deterministic_and_lowercase():
    assert hex_prefix(7, "chat", 6) == hex_prefix(7, "chat", 6)
    assert hex_prefix(7, "chat", 6) != hex_prefix(7, "qa", 6)
    assert len(hex_prefix(7, "chat", 6)) == 6
    assert hex_prefix(7, "chat", 0) == ""
    assert hex_prefix(7, "chat", 6) == hex_prefix(7, "chat", 6).lower()


@pytest.mark.parametrize(
    ("count", "pool", "expected"),
    [
        (0, 1000, 0),
        (25, 1000, 0),
        (1000, 1000, 0),
        (1001, 1000, 1),
        (16_000, 1000, 1),  # 16000/16 = 1000 <= pool
        (16_001, 1000, 2),
        (5_000_000, 1000, 4),
    ],
)
def test_choose_prefix_length(count, pool, expected):
    assert choose_prefix_length(count, pool) == expected


# ── seeded selection ─────────────────────────────────────────────────────────


def _pool(ids: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"unit_id": ids, "sha256": [i * 64 for i in ids]})


def test_select_sample_size_and_determinism():
    pool = _pool([f"u{i:03d}" for i in range(200)])
    a = select_sample(pool, 25, seed=1)
    b = select_sample(pool, 25, seed=1)
    assert len(a) == 25
    assert list(a.unit_id) == list(b.unit_id)


def test_select_sample_order_independent():
    pool = _pool([f"u{i:03d}" for i in range(100)])
    shuffled = pool.sample(frac=1.0, random_state=99).reset_index(drop=True)
    a = set(select_sample(pool, 25, seed=1).unit_id)
    b = set(select_sample(shuffled, 25, seed=1).unit_id)
    assert a == b


def test_select_sample_short_pool_takes_all():
    pool = _pool(["a", "b"])
    assert len(select_sample(pool, 25, seed=1)) == 2


# ── source reconstruction ────────────────────────────────────────────────────


def test_build_source_text_jira_with_comments():
    doc = {
        "title": "HBASE-1",
        "body": "fails intermittently",
        "comments": [{"body": "cannot reproduce"}, {"body": "fixed"}],
    }
    text = build_source_text(doc, "jira_issue")
    assert "HBASE-1" in text and "fails intermittently" in text
    assert "cannot reproduce" in text and "fixed" in text


def test_build_source_text_chat_returns_message_only():
    assert build_source_text({"text": "I have no idea"}, "chat") == "I have no idea"
    assert build_source_text({"content": "hmm"}, "irc") == "hmm"


def test_build_source_text_email_uses_subject_and_body():
    doc = {"headers": {"subject": "Re: patch"}, "body_text": "not sure this works"}
    text = build_source_text(doc, "email")
    assert text == "Re: patch\n\nnot sure this works"


def test_build_source_text_github_issue_with_comments():
    doc = {
        "title": "crash",
        "body": "maybe a race",
        "comments_data": [{"body": "unclear"}],
        "issue_comments_data": [{"body": "still unknown"}],
    }
    text = build_source_text(doc, "issue")
    assert all(s in text for s in ("crash", "maybe a race", "unclear", "still unknown"))


def test_build_source_text_none_and_empty():
    assert build_source_text(None, "chat") == ""
    assert build_source_text({}, "chat") == ""


# ── mongo source routing ─────────────────────────────────────────────────────


def test_source_lookup_email_uses_urn():
    coll, query = source_lookup(
        {"record_id": "email:urn:uuid:1", "urn": "urn:uuid:1", "artefact_kind": "email"}
    )
    assert coll == "raw_emails"
    assert query == {"urn": "urn:uuid:1"}


def test_source_lookup_external_uses_record_id():
    coll, query = source_lookup(
        {
            "record_id": "jira_issue:apachejira:HBASE-1",
            "artefact_kind": "jira_issue",
            "platform_id": "jira",
        }
    )
    assert coll == "raw_external"
    assert query == {"record_id": "jira_issue:apachejira:HBASE-1"}


def test_source_lookup_chat_and_so_are_external():
    for kind, platform in (("chat", "slack"), ("so_question", "stackoverflow")):
        coll, _ = source_lookup(
            {"record_id": "x:1", "artefact_kind": kind, "platform_id": platform}
        )
        assert coll == "raw_external"


def test_source_lookup_github_shaped_by_kind():
    coll, query = source_lookup({"record_id": "openment:p:1", "artefact_kind": "issue"})
    assert coll == "raw_issues"
    assert {"record_id": "openment:p:1"} in query["$or"]
    coll_pr, _ = source_lookup({"record_id": "openment:p:2", "artefact_kind": "pull_request"})
    assert coll_pr == "raw_pull_requests"


def test_source_lookup_missing_record_id():
    assert source_lookup({"artefact_kind": "chat"}) == (None, None)


# ── marker aggregation ───────────────────────────────────────────────────────


def test_layer_counts_includes_zeros_and_totals():
    counts = layer_counts(["lexical", "lexical", "morpho_syntactic", "unknown_layer"])
    assert counts == {
        "n_lexical": 2,
        "n_morpho_syntactic": 1,
        "n_word_formation": 0,
        "n_rhetorical": 0,
    }


# ── xlsx export ──────────────────────────────────────────────────────────────


def test_excel_safe_strips_controls_and_truncates():
    df = pd.DataFrame(
        {
            "unit_text": ["ok\x00with\x01control", "x" * 50],
            "n_markers_total": [3, 1],
        }
    )
    out = excel_safe(df, limit=20)
    assert out.unit_text.iloc[0] == "okwithcontrol"
    assert out.unit_text.iloc[1] == "x" * 20
    assert out.n_markers_total.tolist() == [3, 1]


def test_write_workbook_roundtrip(tmp_path):
    df = pd.DataFrame(
        {
            "genre": ["tracker", "chat"],
            "unit_id": ["openment:p:1:body", "irc:c:1:message"],
            "unit_text": ["maybe a race", "no idea"],
            "n_markers_total": [2, 1],
        }
    )
    path = write_workbook(df, tmp_path / "sample.xlsx")
    assert path.exists()
    back = pd.read_excel(path)
    assert list(back.columns) == list(df.columns)
    assert back.unit_text.tolist() == ["maybe a race", "no idea"]
    assert back.n_markers_total.tolist() == [2, 1]
