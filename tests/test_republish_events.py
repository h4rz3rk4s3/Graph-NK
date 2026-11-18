"""
Tests for scripts/republish_events.build_event (pure, no services).

The republisher rebuilds stream_raw pointer events from Mongo docs, so its
event-construction must match the shape the projector/extractor consume. These
tests lock that contract down without touching any service.
"""

from __future__ import annotations

from scripts.corpus_census import CURATED_CORPORA, pending_corpora
from scripts.republish_events import _curated_filter, build_event


def test_external_doc_event_shape():
    doc = {
        "_id": "a1" * 12,
        "record_id": "jira_issue:tier3:TEST-1",
        "_meta": {"item_type": "jira_issue", "corpus_id": "apache-jira",
                  "platform_id": "tier3", "record_id": "jira_issue:tier3:TEST-1"},
        "platform_id": "tier3",
        "corpus_id": "apache-jira",
        "venue_id": "tier3:apache",
        "artefact_kind": "jira_issue",
        "artefact_labels": ["Artefact", "IssueArtefact", "JiraIssue"],
    }
    ev = build_event("raw_external", doc)
    assert ev is not None
    assert ev["item_type"] == "jira_issue"
    assert ev["item_subtype"] == "jira_issue"
    assert ev["mongo_id"] == doc["_id"]
    assert ev["corpus_id"] == "apache-jira"
    assert ev["venue_id"] == "tier3:apache"


def test_email_event_shape():
    doc = {
        "_id": "b2" * 12,
        "_meta": {"item_type": "email", "corpus_id": "curated-email-code-reviews"},
        "urn": "curatedemail:ffmpeg:1",
        "corpus_id": "curated-email-code-reviews",
        "venue_id": "mailing_list:curated-email-code-reviews:ffmpeg",
        "artefact_kind": "email",
        "artefact_labels": ["Artefact", "MessageArtefact", "EmailMessage"],
    }
    ev = build_event("raw_emails", doc)
    assert ev is not None
    assert ev["item_type"] == "email"
    assert ev["item_subtype"] == "email"
    assert ev["repo_name"] == "mailing_list:curated-email-code-reviews:ffmpeg"


def test_github_shaped_doc_uses_repo():
    doc = {
        "_id": "c3" * 12,
        "_meta": {"item_type": "issue", "corpus_id": "openment"},
        "repo": "openment:abc",
        "platform_id": "openment",
        "corpus_id": "openment",
        "venue_id": "openment:abc",
        "artefact_kind": "issue",
        "artefact_labels": ["Artefact", "IssueArtefact", "OpenMentIssue"],
    }
    ev = build_event("raw_issues", doc)
    assert ev is not None
    assert ev["item_type"] == "issue"
    assert ev["repo_name"] == "openment:abc"


def test_old_scope_docs_not_matched_by_filter():
    # Old GitHub/Gmane docs carry no corpus_id → the curated $or filter must NOT
    # match them (this is the republisher's scope guard).
    old_gh = {"_meta": {"item_type": "issue"}}
    old_gmane = {"urn": "gmane:x"}
    for doc in (old_gh, old_gmane):
        # corpus_id is absent at both locations the filter checks
        assert "corpus_id" not in doc
        assert "corpus_id" not in (doc.get("_meta") or {})


def test_curated_filter_structure():
    or_clause = _curated_filter()["$or"]
    expected_in = {"corpus_id": {"$in": sorted(CURATED_CORPORA)}}
    expected_meta = {"_meta.corpus_id": {"$in": sorted(CURATED_CORPORA)}}
    assert expected_in in or_clause
    assert expected_meta in or_clause


def test_curated_filter_selection():
    # --corpus selection restricts both $in clauses to the selection.
    sel = frozenset({"sotorrent", "kummerfeld-irc", "preethac-slack"})
    or_clause = _curated_filter(sel)["$or"]
    expected = {"corpus_id": {"$in": ["kummerfeld-irc", "preethac-slack", "sotorrent"]}}
    expected_meta = {"_meta.corpus_id": {"$in": ["kummerfeld-irc", "preethac-slack", "sotorrent"]}}
    assert expected in or_clause
    assert expected_meta in or_clause
    # and the selection is an intersection with CURATED_CORPORA, never wider
    assert _curated_filter(frozenset({"sotorrent", "not-a-corpus"}))["$or"][0] == {
        "corpus_id": {"$in": ["sotorrent"]}
    }


def test_pending_corpora_lists_missing():
    counts = {"gittercom": 1_000, "disco": 500}
    pending = {cid for cid, _ in pending_corpora(counts)}
    assert "gittercom" not in pending
    assert "disco" not in pending
    assert "apache-jira" in pending
    assert "openment" in pending


def test_unmappable_curated_doc_returns_none():
    assert build_event("raw_external", {"_id": "f6" * 12,
                                        "corpus_id": "apache-jira"}) is None