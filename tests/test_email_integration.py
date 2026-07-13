"""
Tests for the Gmane email integration (v0.6).

IMPORTANT: written WITHOUT access to real corpus files. Synthetic records are
constructed strictly from the Webis documentation (ES bulk line pairs, header
set, segment classes). When real data arrives, add one genuine record here as a
golden sample and re-run — see CHANGELOG 2026-06-04 (v0.6) assumptions A1–A3.

Pure-Python: no spaCy, Mongo, Redis, or Neo4j required.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from miner.gmane_ingester import _clean_urn, iter_bulk_records, record_in_scope


# ── Synthetic corpus data (documented format) ─────────────────────────────────

BODY = (
    "Hi all,\n\n"                                                    # salutation 0..8
    "I'm not sure whether this patch fixes the race condition.\n\n"  # paragraph 9..67
    "> Previously someone wrote: this is unclear to me too\n\n"      # quotation 68..121
    "Cheers,\nAlice\n"                                               # closing 122..136
)

EMAIL_DOC = {
    "headers": {
        "message_id": "<msg-002@example.org>",
        "date": "2019-03-14 09:26:53+00:00",
        "subject": "Re: Race condition in scheduler?",
        "from": "anon-7f3a9",
        "to": "list@example.org",
        "in_reply_to": "<msg-001@example.org>",
        "references": "<msg-001@example.org>",
        "list_id": "<dev.example.org>",
    },
    "text_plain": BODY,
    "lang": "en",
    "segments": [
        {"begin": 0,   "end": 8,   "label": "salutation"},
        {"begin": 9,   "end": 67,  "label": "paragraph"},
        {"begin": 68,  "end": 121, "label": "quotation"},
        {"begin": 122, "end": 136, "label": "closing"},
    ],
    "group": "gmane.comp.example.devel",
}


def _write_corpus_file(tmp_path: Path, records: list[tuple[str, dict]]) -> str:
    """Write records as a gzip ES-bulk file (the documented on-disk format)."""
    path = tmp_path / "corpus.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for urn, doc in records:
            fh.write(json.dumps({"index": {"_id": f"<{urn}>"}}) + "\n")
            fh.write(json.dumps(doc) + "\n")
    return str(path)


# ── Parser tests ──────────────────────────────────────────────────────────────

def test_clean_urn_strips_angle_brackets():
    assert _clean_urn("<urn:uuid:abc>") == "urn:uuid:abc"
    assert _clean_urn("urn:uuid:abc") == "urn:uuid:abc"


def test_iter_bulk_records_roundtrip(tmp_path):
    path = _write_corpus_file(tmp_path, [
        ("urn:uuid:0001", EMAIL_DOC),
        ("urn:uuid:0002", {**EMAIL_DOC, "lang": "de"}),
    ])
    records = list(iter_bulk_records(path))
    assert [u for u, _ in records] == ["urn:uuid:0001", "urn:uuid:0002"]
    assert records[0][1]["group"] == "gmane.comp.example.devel"


def test_iter_bulk_records_resyncs_after_malformed_line(tmp_path, caplog):
    path = tmp_path / "bad.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"index": {"_id": "<urn:uuid:0001>"}}) + "\n")
        fh.write("{this is not json\n")                                   # breaks pair
        fh.write(json.dumps({"index": {"_id": "<urn:uuid:0002>"}}) + "\n")
        fh.write(json.dumps(EMAIL_DOC) + "\n")                            # good pair
    records = list(iter_bulk_records(str(path)))
    assert [u for u, _ in records] == ["urn:uuid:0002"]  # bad pair skipped, good one kept


def test_record_in_scope_filters():
    assert record_in_scope(EMAIL_DOC, None, None)
    assert record_in_scope(EMAIL_DOC, {"gmane.comp.example.devel"}, {"en"})
    assert not record_in_scope(EMAIL_DOC, {"gmane.other.group"}, None)
    assert not record_in_scope(EMAIL_DOC, None, {"de"})


# ── Extractor tests ───────────────────────────────────────────────────────────

def _extract(doc=None):
    from extractor.text_unit_extractor import extract_from_email
    d = dict(EMAIL_DOC if doc is None else doc)
    d["urn"] = "urn:uuid:0001"  # ingester stores urn on the doc
    return extract_from_email(d, repo="gmane:gmane.comp.example.devel")


def test_email_units_subject_and_paragraph_only():
    units = _extract()
    roles = [u.role for u in units]
    # subject + the single allowed 'paragraph' segment; default allowlist
    # excludes salutation, quotation, closing.
    assert roles == ["subject", "paragraph"]


def test_quotation_is_never_extracted():
    """Methodological invariant: quoted text must not produce TextUnits —
    it repeats the previous author's words and would duplicate NK signals."""
    units = _extract()
    for u in units:
        assert "unclear to me too" not in u.text, "quotation leaked into TextUnits"


def test_email_unit_ids_and_parenting():
    units = _extract()
    subject, para = units
    assert subject.text_unit_id == "email:urn:uuid:0001:subject"
    assert para.text_unit_id == "email:urn:uuid:0001:paragraph:1"
    assert all(u.parent_type == "email" for u in units)
    assert all(u.parent_id == "email:urn:uuid:0001" for u in units)
    assert all(u.author_login == "anon-7f3a9" for u in units)
    assert all(u.lang == "en" for u in units)  # corpus lang is authoritative


def test_email_paragraph_text_matches_span():
    units = _extract()
    para = units[1]
    assert para.text == BODY[9:67].strip()
    assert "not sure whether" in para.text


def test_out_of_bounds_segment_is_skipped_not_fatal():
    doc = dict(EMAIL_DOC)
    doc["segments"] = EMAIL_DOC["segments"] + [{"begin": 9000, "end": 9100, "label": "paragraph"}]
    units = _extract(doc)
    assert [u.role for u in units] == ["subject", "paragraph"]  # bad span ignored


def test_missing_urn_yields_no_units():
    from extractor.text_unit_extractor import extract_from_email
    assert extract_from_email(dict(EMAIL_DOC), repo="gmane:x") == []


def test_segment_allowlist_is_configurable(monkeypatch):
    from settings import settings as s
    monkeypatch.setattr(s, "email_segment_labels", ["paragraph", "closing"])
    units = _extract()
    assert [u.role for u in units] == ["subject", "paragraph", "closing"]
