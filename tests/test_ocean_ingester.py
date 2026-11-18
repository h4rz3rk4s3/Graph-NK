"""
Tests for the OCEAN dataset ingestion path (v0.8).

Pure-Python: no spaCy, Mongo, Redis, or Neo4j required. Synthetic OCEAN records
are constructed from the real column set verified in email_eda.ipynb, and are
written to a tiny tmp_path JSONL so the build agent NEVER touches the real
multi-GB ocean_dataset/ files.

Covers the ingester (miner/ocean_ingester.py), the OCEAN-specific extractor
(extractor.text_unit_extractor.extract_from_ocean_email), and the corpus
dispatch (extract_email_for_corpus) that the extractor worker relies on.
"""

from __future__ import annotations

import json
from pathlib import Path

from extractor.text_unit_extractor import (
    extract_email_for_corpus,
    extract_from_ocean_email,
)
from miner.ocean_ingester import (
    build_headers,
    derive_urn,
    iter_ocean_records,
    record_in_scope,
    to_email_doc,
)

# ── Synthetic OCEAN record (real column set; see email_eda.ipynb) ─────────────

OCEAN_FLAT = {
    "old_index": 0,
    "from_name": "elad volpin",
    "from_email": "eladv...@gmail.com",
    "raw_from_string": "Elad Volpin <eladv...@gmail.com>",
    "to_name": "angular and angularjs discussion",
    "to_email": "ang...@googlegroups.com",
    "raw_to_string": "Angular and AngularJS discussion <ang...@googlegroups.com>",
    "cc_name": None,
    "cc_email": None,
    "raw_cc_string": None,
    "subject": "Angular 10, sometimes fails to load vendor.js",
    "date": 1617874501000,
    "raw_date_string": "Thu, 8 Apr 2021 02:35:01 -0700 (PDT)",
    "message_id": "<6e3c2602-c3a8-4683-9b0d-9dacb6e55106n@googlegroups.com>",
    "in_reply_to": "<parent-msg@googlegroups.com>",
    "refs": ["<parent-msg@googlegroups.com>", "<grandparent-msg@googlegroups.com>"],
    "raw_refs_string": "<parent-msg@...> <grandparent-msg@...>",
    "body_text": (
        "Hi,\n\n"
        "I'm not sure whether the scripts time out.\n\n"
        "> Previously someone wrote: this is unclear to me too\n"
        "Any idea how to solve this?"
    ),
    "body_html": "<div>Hi</div>",
    "body_image": None,
    "content_type": "text/plain",
    "mailing_list": "angular",
    "filename": "angular_clean.jsonl",
    "time_stamp": 1617874501,
    "week": 14,
    "month": 4,
    "day": 8,
    "year": 2021,
}


def _write_jsonl(tmp_path: Path, records: list[dict]) -> str:
    path = tmp_path / "ocean.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    return str(path)


# ── Parser tests ──────────────────────────────────────────────────────────────


def test_iter_ocean_records_roundtrip(tmp_path):
    path = _write_jsonl(tmp_path, [OCEAN_FLAT, {**OCEAN_FLAT, "message_id": "<two>"}])
    docs = list(iter_ocean_records(path))
    assert len(docs) == 2
    assert docs[0]["message_id"] == OCEAN_FLAT["message_id"]
    assert docs[1]["message_id"] == "<two>"


def test_iter_ocean_records_skips_blank_and_malformed(tmp_path, caplog):
    path = tmp_path / "ocean.jsonl"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(OCEAN_FLAT) + "\n")
        fh.write("\n")  # blank line
        fh.write("{this is not json\n")  # malformed line
        fh.write(json.dumps({**OCEAN_FLAT, "message_id": "<three>"}) + "\n")
    docs = list(iter_ocean_records(str(path)))
    assert [d["message_id"] for d in docs] == [OCEAN_FLAT["message_id"], "<three>"]


# ── urn derivation ────────────────────────────────────────────────────────────


def test_derive_urn_is_namespaced():
    assert derive_urn(OCEAN_FLAT) == (
        "ocean:angular:<6e3c2602-c3a8-4683-9b0d-9dacb6e55106n@googlegroups.com>"
    )


def test_derive_urn_disambiguates_same_message_id_across_lists():
    a = derive_urn({**OCEAN_FLAT, "mailing_list": "angular"})
    b = derive_urn({**OCEAN_FLAT, "mailing_list": "golang"})
    assert a != b


def test_derive_urn_falls_back_to_hash_without_message_id():
    urn = derive_urn({k: v for k, v in OCEAN_FLAT.items() if k != "message_id"})
    assert urn.startswith("ocean:angular:")
    assert "message_id" not in urn


# ── headers mapping ───────────────────────────────────────────────────────────


def test_build_headers_maps_flat_fields():
    h = build_headers(OCEAN_FLAT)
    assert h["from"] == "Elad Volpin <eladv...@gmail.com>"
    assert h["to"] == "Angular and AngularJS discussion <ang...@googlegroups.com>"
    assert h["subject"] == OCEAN_FLAT["subject"]
    assert h["date"] == OCEAN_FLAT["raw_date_string"]
    assert h["message_id"] == OCEAN_FLAT["message_id"]
    assert h["in_reply_to"] == OCEAN_FLAT["in_reply_to"]
    assert h["references"] == OCEAN_FLAT["refs"]


def test_build_headers_omits_absent_fields():
    h = build_headers({})
    assert h == {}


# ── doc wrapping ──────────────────────────────────────────────────────────────


def test_to_email_doc_shape():
    doc = to_email_doc(OCEAN_FLAT)
    assert doc["urn"] == derive_urn(OCEAN_FLAT)
    assert doc["group"] == "angular"
    assert doc["lang"] == "en"
    assert doc["headers"]["from"] == OCEAN_FLAT["raw_from_string"]
    # source fields preserved verbatim for the OCEAN extractor
    assert doc["body_text"] == OCEAN_FLAT["body_text"]
    assert doc["subject"] == OCEAN_FLAT["subject"]
    assert doc["_meta"]["item_type"] == "email"
    assert doc["_meta"]["processed"] is False
    assert doc["_meta"]["content_sha256"]


# ── scope filter ──────────────────────────────────────────────────────────────


def test_record_in_scope():
    assert record_in_scope(OCEAN_FLAT, None)
    assert record_in_scope(OCEAN_FLAT, {"angular"})
    assert not record_in_scope(OCEAN_FLAT, {"golang"})


# ── OCEAN extractor integration ───────────────────────────────────────────────


def _ocean_doc():
    return to_email_doc(OCEAN_FLAT)


def test_extract_ocean_email_subject_and_body_units():
    units = extract_from_ocean_email(_ocean_doc(), repo="ocean:angular")
    roles = [u.role for u in units]
    assert roles == ["subject", "body"]
    assert [u.position for u in units] == [0, 1]
    assert all(u.parent_type == "email" for u in units)
    assert all(u.lang == "en" for u in units)


def test_extract_ocean_email_parent_id_uses_email_convention():
    urn = derive_urn(OCEAN_FLAT)
    units = extract_from_ocean_email(_ocean_doc(), repo="ocean:angular")
    assert all(u.parent_id == f"email:{urn}" for u in units)


def test_extract_ocean_email_author_and_date():
    units = extract_from_ocean_email(_ocean_doc(), repo="ocean:angular")
    assert all(u.author_login == "Elad Volpin <eladv...@gmail.com>" for u in units)
    assert all(u.created_at == OCEAN_FLAT["raw_date_string"] for u in units)


def test_extract_ocean_email_strips_quoted_lines_from_body():
    """Quoted lines (previous author's words) must not become NK text — the
    strip_text contract used by every extractor (extractor/text_unit_extractor)."""
    units = extract_from_ocean_email(_ocean_doc(), repo="ocean:angular")
    body = [u for u in units if u.role == "body"][0]
    assert "Previously someone wrote" not in body.text
    assert "Any idea how to solve this?" in body.text


def test_extract_ocean_email_empty_body_yields_subject_only():
    doc = {**_ocean_doc(), "body_text": ""}
    units = extract_from_ocean_email(doc, repo="ocean:angular")
    assert [u.role for u in units] == ["subject"]


def test_extract_ocean_email_missing_urn_yields_no_units():
    doc = {k: v for k, v in _ocean_doc().items() if k != "urn"}
    assert extract_from_ocean_email(doc, repo="ocean:angular") == []


def test_extract_ocean_email_empty_message_yields_no_units():
    doc = {**_ocean_doc(), "subject": "", "body_text": ""}
    assert extract_from_ocean_email(doc, repo="ocean:angular") == []


# ── corpus dispatch (worker routing) ──────────────────────────────────────────


def test_extract_email_for_corpus_routes_ocean_to_ocean_extractor():
    doc = _ocean_doc()
    units = extract_email_for_corpus(doc, repo="ocean:angular")
    # subject + body units (message granularity), not segment-derived paragraphs
    assert [u.role for u in units] == ["subject", "body"]


def test_extract_email_for_corpus_routes_non_ocean_to_gmane_extractor():
    doc = {
        "urn": "urn:uuid:0001",
        "headers": {
            "subject": "Re: race",
            "from": "anon-1",
            "date": "2019-01-01",
        },
        "text_plain": "not sure about this race.",
        "lang": "en",
        "segments": [
            {"begin": 0, "end": 26, "label": "paragraph"},
        ],
    }
    units = extract_email_for_corpus(doc, repo="gmane:gmane.comp.example.devel")
    roles = [u.role for u in units]
    # gmane path yields segment-derived paragraph roles, not ocean "body"
    assert roles == ["subject", "paragraph"]
