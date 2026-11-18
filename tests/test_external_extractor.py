"""
Tests for the v0.8 external-artefact extractors (pure, no services).

These exercise extract_from_jira_issue / extract_from_bugzilla_issue /
extract_from_chat_message / extract_from_so_post and the curated-email routing.
Pure-Python: no spaCy, Mongo, Redis, or Neo4j required.
"""

from __future__ import annotations

from extractor.text_unit_extractor import (
    extract_email_for_corpus,
    extract_from_bugzilla_issue,
    extract_from_chat_message,
    extract_from_jira_issue,
    extract_from_so_post,
)


def test_jira_issue_roles_and_parenthood():
    doc = {
        "record_id": "jira_issue:apachejira:HBASE-1",
        "summary": "the title",
        "description": "the body",
        "comments": [{"body": "a comment", "author_login": "jira:apachejira:u"}],
        "author_login": "jira:apachejira:o",
        "created_at": "2020-01-01",
    }
    units = extract_from_jira_issue(doc, "jira:apachejira:HBASE")
    assert [u.role for u in units] == ["title", "body", "comment_body"]
    assert all(u.parent_type == "jira_issue" for u in units)
    assert all(u.parent_id == "jira_issue:apachejira:HBASE-1" for u in units)
    assert units[0].position == 0 and units[1].position == 1 and units[2].position == 2
    assert units[2].author_login == "jira:apachejira:u"


def test_jira_title_prefers_title_over_summary():
    doc = {"record_id": "r", "title": "t", "summary": "s", "body": "b", "comments": []}
    units = extract_from_jira_issue(doc, "x")
    assert units[0].text == "t"


def test_jira_missing_record_id_yields_nothing():
    assert extract_from_jira_issue({"summary": "s"}, "x") == []


def test_bugzilla_issue_shapes_comments():
    doc = {
        "record_id": "bugzilla_issue:bugsrepo:99",
        "summary": "title",
        "description": "body",
        "comments": [
            {"body": "c1", "author_login": "bugzilla:bugsrepo:a", "created_at": None},
            {"body": "", "author_login": None, "created_at": None},  # empty -> dropped
        ],
    }
    units = extract_from_bugzilla_issue(doc, "bugzilla:bugsrepo:mozilla")
    assert [u.role for u in units] == ["title", "body", "comment_body"]
    assert all(u.parent_type == "bugzilla_issue" for u in units)


def test_chat_message_single_unit_role_message():
    doc = {"record_id": "chat_message:discord:disco:1", "text": "is this server dead?"}
    units = extract_from_chat_message(doc, "discord:disco:x")
    assert [(u.role, u.position, u.parent_type) for u in units] == [("message", 0, "chat_message")]
    assert units[0].parent_id == "chat_message:discord:disco:1"


def test_so_post_title_and_body():
    doc = {"record_id": "so_post:so-emotion-gold:1", "title": "Q", "text": "Question body"}
    units = extract_from_so_post(doc, "stackoverflow:so")
    assert [u.role for u in units] == ["title", "body"]
    # body position follows the title
    title, body = units
    assert title.position == 0 and body.position == 1


def test_so_post_body_only():
    doc = {"record_id": "so_post:x:2", "text": "Just a body"}
    units = extract_from_so_post(doc, "stackoverflow:so")
    assert [u.role for u in units] == ["body"]
    assert units[0].position == 0


def test_curated_email_routes_to_ocean_extractor():
    """The "curatedemail:" namespace must use the OCEAN message-granularity
    extractor (flat subject/body_text, no segment spans)."""
    doc = {
        "urn": "curatedemail:ffmpeg:something",
        "subject": "Re: patch",
        "body_text": "the review body",
        "raw_from_string": "A. Author",
        "raw_date_string": "2019-06-11 16:25:29",
        "lang": "en",
        "headers": {"subject": "Re: patch", "from": "A. Author"},
    }
    units = extract_email_for_corpus(doc, "curatedemail:ffmpeg")
    assert [u.role for u in units] == ["subject", "body"]
    assert all(u.lang == "en" for u in units)
    assert all(u.parent_type == "email" for u in units)


def test_curated_email_body_text_used():
    from extractor.text_unit_extractor import extract_email_for_corpus

    doc = {
        "urn": "curatedemail:kernel:x",
        "subject": "S",
        "body_text": "   body   ",
        "headers": {"subject": "S"},
    }
    body_units = [
        u for u in extract_email_for_corpus(doc, "curatedemail:kernel") if u.role == "body"
    ]
    assert body_units and body_units[0].text == "body"
