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


# ── Offset-convention detection (v0.6.1) ──────────────────────────────────────
# Real Gmane data produced "segment span out of bounds" despite Webis
# documenting these as character spans (see CHANGELOG 2026-07-14, v0.6.1).
# extract_from_email detects, per EMAIL, which single offset convention makes
# every one of that email's segments valid, and applies it uniformly — rather
# than guessing per segment, which has a real silent-corruption failure mode
# (see test_document_level_detection_avoids_silent_misalignment below).

def _email_with_segments(text: str, spans: list[tuple[int, int, str]]) -> dict:
    """Build a minimal email doc with given (begin, end, label) segments."""
    return {
        "urn": "urn:uuid:offset-test",
        "headers": {"subject": "test", "from": "anon-1", "date": "2019-01-01"},
        "text_plain": text,
        "lang": "en",
        "group": "gmane.test",
        "segments": [{"begin": b, "end": e, "label": lbl} for b, e, lbl in spans],
    }


def test_char_offsets_used_as_is_when_valid():
    text = "Hello world, this is a test."
    doc = _email_with_segments(text, [(0, 5, "paragraph")])
    from extractor.text_unit_extractor import extract_from_email
    units = extract_from_email(doc, repo="gmane:x")
    para = [u for u in units if u.role == "paragraph"][0]
    assert para.text == "Hello"


def test_utf8_byte_offset_convention_recovered_for_whole_email():
    """All segments in a document encoded as UTF-8 byte offsets (e.g. a
    byte-counting segmenter) must all be recovered correctly, including ones
    early in the document with only small drift."""
    words = ["alpha", "bravo", "charlie", "delta"]
    text = " — ".join(words) + " end."  # em-dash: 3 UTF-8 bytes, 1 codepoint

    def byte_span(word):
        cb = text.index(word)
        ce = cb + len(word)
        return len(text[:cb].encode("utf-8")), len(text[:ce].encode("utf-8"))

    doc = _email_with_segments(text, [(*byte_span(w), "paragraph") for w in words])
    from extractor.text_unit_extractor import extract_from_email
    units = extract_from_email(doc, repo="gmane:x")
    recovered = [u.text for u in units if u.role == "paragraph"]
    assert recovered == words, f"expected {words}, got {recovered}"


def test_document_level_detection_avoids_silent_misalignment():
    """
    Regression test for a real design flaw caught during development: a
    naive PER-SEGMENT resolver that tries 'char' first and accepts whatever
    is in-bounds will, for an early segment with only small byte-offset
    drift, silently accept the WRONG (misaligned) substring — because the
    wrong interpretation still happens to fall within the document's length.
    Document-level majority-vote detection avoids this: the early segment
    alone can't be told apart from a truly char-offset one, but its later
    siblings in the SAME document accumulate enough byte-offset drift to
    exceed the document's length under naive char reading, which forces the
    correct convention — and that convention is then applied uniformly,
    correcting the early segment too even though it looked fine in isolation.

    (Detection is bounds-based, so it necessarily needs cumulative drift to
    exceed the document's own length by the time of some segment — exactly
    the condition met by every email in the real corpus that is currently
    producing "segment span out of bounds" warnings. See CHANGELOG
    2026-07-14, v0.6.1, for the documented limitation this implies for
    documents where drift never gets that large.)
    """
    # 20 repetitions of an em-dash (3 UTF-8 bytes, 1 codepoint) between
    # "alpha" and the rest accumulate +40 bytes of drift — enough to push
    # later byte-offset segments past this (short) document's char length.
    noise = " — x" * 20
    text = "alpha" + noise + " bravo charlie delta end."

    def byte_span(word: str, occurrence: int = 0) -> tuple[int, int]:
        idx = -1
        for _ in range(occurrence + 1):
            idx = text.index(word, idx + 1)
        return len(text[:idx].encode("utf-8")), len(text[:idx + len(word)].encode("utf-8"))

    early = byte_span("alpha")   # drift = 0 here; would "validate" under ANY convention
    late = byte_span("delta")    # drift is large enough to force correct detection

    doc = _email_with_segments(text, [(*early, "paragraph"), (*late, "paragraph")])
    from extractor.text_unit_extractor import extract_from_email
    units = extract_from_email(doc, repo="gmane:x")
    paragraphs = [u.text for u in units if u.role == "paragraph"]
    assert "alpha" in paragraphs, f"early segment was silently misaligned: got {paragraphs}"
    assert "delta" in paragraphs, f"late segment failed to resolve: got {paragraphs}"


def test_isolated_bad_segment_dropped_without_losing_valid_siblings():
    """When most of a document's segments agree on one convention, a single
    outlier segment that fits NO convention is dropped individually — it must
    not take down the other, genuinely valid segments in the same document
    (majority-vote design; see CHANGELOG 2026-07-14 v0.6.1)."""
    text = "short"
    doc = _email_with_segments(text, [(0, 3, "paragraph"), (9999, 10005, "paragraph")])
    from extractor.text_unit_extractor import extract_from_email
    units = extract_from_email(doc, repo="gmane:x")
    roles_and_text = [(u.role, u.text) for u in units]
    assert ("paragraph", "sho") in roles_and_text  # the valid segment survives
    assert len(units) == 2  # subject + the one valid paragraph; bad one dropped


def test_trailing_one_char_overshoot_is_recovered_not_dropped():
    """Confirmed against real corpus data (v0.6.2): a segment ending exactly
    1 character past text_plain's length — almost always a trailing newline
    present when segmentation ran but stripped from the exported text — is
    recovered by clamping to the true length, rather than discarding the
    whole segment for one missing character."""
    text = "Not sure if this is expected behavior or a bug."
    doc = _email_with_segments(text, [(0, len(text) + 1, "paragraph")])  # off-by-one
    from extractor.text_unit_extractor import extract_from_email
    units = extract_from_email(doc, repo="gmane:x")
    paragraphs = [u.text for u in units if u.role == "paragraph"]
    assert paragraphs == [text], f"expected recovered full text, got {paragraphs}"


def test_large_overshoot_is_still_dropped_not_masked():
    """The trailing-overshoot clamp is deliberately narrow (<=2 chars) so it
    cannot hide genuine truncation — a segment that's meaningfully cut off
    must still be skipped and warned about, not silently accepted."""
    text = "Short paragraph."
    doc = _email_with_segments(text, [(0, len(text) + 50, "paragraph")])  # big overshoot
    from extractor.text_unit_extractor import extract_from_email
    units = extract_from_email(doc, repo="gmane:x")
    assert [u.role for u in units] == ["subject"]  # paragraph correctly dropped

