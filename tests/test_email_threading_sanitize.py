"""
Tests for the projector's email threading-header sanitizer.

Covers _sanitize_email_threading (projector/graph_projector.py), the pure
function that normalizes `in_reply_to` for the curated email corpora before it
is written to Neo4j (CHANGELOG 2026-08-24). Self-contained — no services.

Why this exists: the curated email .jl records carry `in_reply_to` as either a
single string or a list of ancestor message-ids. A list value (a) trips Neo4j's
~8 KB RANGE-index cap on `email_in_reply_to`, aborting the whole Phase-1 batch,
and (b) silently yields zero REPLIES_TO edges because the threading enrichment
matches `parent.message_id = reply.in_reply_to` exactly. The sanitizer turns a
single distinct bracketed id (after dropping the message's own id) into the
direct parent, and otherwise demotes the ids to `references`.
"""

from __future__ import annotations

from projector.graph_projector import _sanitize_email_threading


def test_string_in_reply_to_single_stripped():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", "  <parent@x>  ", None)
    assert msg == "<mid@x>"
    assert irt == "<parent@x>"
    assert refs is None


def test_list_single_distinct_is_parent():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", ["<parent@x>", "<parent@x>"], None)
    assert irt == "<parent@x>"
    assert refs is None


def test_list_multi_distinct_demotes_to_references():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", ["<a@x>", "<b@x>", "<a@x>"], None)
    assert irt is None
    assert refs == ["<a@x>", "<b@x>"]  # order-preserving dedupe


def test_list_whitespace_padded_tokens_stripped():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", [" \n <a@x>", "\n <b@x>"], None)
    assert irt is None
    assert refs == ["<a@x>", "<b@x>"]


def test_list_own_message_id_excluded():
    msg, irt, refs = _sanitize_email_threading("<self@x>", ["<self@x>", "<parent@x>"], None)
    assert irt == "<parent@x>"


def test_list_only_own_message_id_gets_no_parent():
    msg, irt, refs = _sanitize_email_threading("<self@x>", ["<self@x>", "<self@x>"], None)
    assert irt is None
    assert refs is None


def test_blank_string_yields_none():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", "   ", None)
    assert irt is None
    assert refs is None


def test_non_bracketed_string_kept_stripped():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", "  bare-id-123  ", None)
    assert irt == "bare-id-123"
    assert refs is None


def test_multi_token_string_demotes_to_references():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", "<a@x> <b@x>", None)
    assert irt is None
    assert refs == ["<a@x>", "<b@x>"]


def test_oversized_single_token_demoted():
    big = "<" + "x" * 1200 + "@h>"
    msg, irt, refs = _sanitize_email_threading("<mid@x>", big, None)
    assert irt is None
    assert refs == [big]


def test_none_in_reply_to_passes_through():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", None, ["<anc@x>"])
    assert irt is None
    assert refs == ["<anc@x>"]  # header references preserved


def test_header_references_preserved_on_demote():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", ["<a@x>", "<b@x>"], ["<existing@x>"])
    assert irt is None
    assert refs == ["<existing@x>"]


def test_message_id_stripped():
    msg, irt, refs = _sanitize_email_threading("  <mid@x>  ", "<parent@x>", None)
    assert msg == "<mid@x>"


def test_non_string_list_entries_ignored():
    msg, irt, refs = _sanitize_email_threading("<mid@x>", ["<a@x>", 42, None, "<a@x>"], None)
    assert irt == "<a@x>"
    assert refs is None
