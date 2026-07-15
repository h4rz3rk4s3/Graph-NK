"""
Tests for the Gmane ingester (v0.6 parser + ingestion-throughput rework).

Covers:
  - Original parser/filter contract (unchanged when group_prefilter is None).
  - The new group-prefilter fast path: never produces a false negative.
  - The batched ingest() flow against fake Mongo/Redis, including the
    upserted_ids-driven "only publish for genuinely new docs" behavior.

Pure-Python: no real Mongo/Redis/Neo4j required (fakes below).
"""
from __future__ import annotations

import asyncio
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from miner.gmane_ingester import (
    _clean_urn,
    _group_prefilter_bytes,
    ingest,
    iter_bulk_records,
    record_in_scope,
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
    "text_plain": (
        "Hi all,\n\n"
        "I'm not sure whether this patch fixes the race condition. " * 5 + "\n\n"
        "Cheers,\nAlice\n"
    ),
    "lang": "en",
    "segments": [
        {"begin": 0, "end": 8, "label": "salutation"},
        {"begin": 9, "end": 300, "label": "paragraph"},
    ],
    "group": "gmane.comp.example.devel",
}


def _write_corpus_file(tmp_path: Path, records: list[tuple[str, dict]]) -> str:
    path = tmp_path / "corpus.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for urn, doc in records:
            fh.write(json.dumps({"index": {"_id": f"<{urn}>"}}) + "\n")
            fh.write(json.dumps(doc) + "\n")
    return str(path)


# ── Original parser contract — unchanged ─────────────────────────────────────

def test_clean_urn_strips_angle_brackets():
    assert _clean_urn("<urn:uuid:abc>") == "urn:uuid:abc"
    assert _clean_urn("urn:uuid:abc") == "urn:uuid:abc"


def test_iter_bulk_records_roundtrip_no_prefilter(tmp_path):
    path = _write_corpus_file(tmp_path, [
        ("urn:uuid:0001", EMAIL_DOC),
        ("urn:uuid:0002", {**EMAIL_DOC, "lang": "de"}),
    ])
    records = list(iter_bulk_records(path))
    assert [u for u, _ in records] == ["urn:uuid:0001", "urn:uuid:0002"]
    assert records[0][1]["group"] == "gmane.comp.example.devel"


def test_iter_bulk_records_resyncs_after_malformed_line(tmp_path):
    path = tmp_path / "bad.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"index": {"_id": "<urn:uuid:0001>"}}) + "\n")
        fh.write("{this is not json\n")
        fh.write(json.dumps({"index": {"_id": "<urn:uuid:0002>"}}) + "\n")
        fh.write(json.dumps(EMAIL_DOC) + "\n")
    records = list(iter_bulk_records(str(path)))
    assert [u for u, _ in records] == ["urn:uuid:0002"]


def test_record_in_scope_filters():
    assert record_in_scope(EMAIL_DOC, None, None)
    assert record_in_scope(EMAIL_DOC, {"gmane.comp.example.devel"}, {"en"})
    assert not record_in_scope(EMAIL_DOC, {"gmane.other.group"}, None)
    assert not record_in_scope(EMAIL_DOC, None, {"de"})


# ── New: group prefilter fast path ────────────────────────────────────────────

def test_group_prefilter_bytes_shape():
    assert _group_prefilter_bytes(None) is None
    assert _group_prefilter_bytes([]) is None
    pf = _group_prefilter_bytes(["gmane.comp.example.devel"])
    assert pf == frozenset({b'"gmane.comp.example.devel"'})


def test_prefilter_never_drops_in_scope_record(tmp_path):
    """The core correctness property: prefilter is necessary-not-sufficient."""
    path = _write_corpus_file(tmp_path, [
        ("urn:uuid:0001", EMAIL_DOC),  # in the allowed group
        ("urn:uuid:0002", {**EMAIL_DOC, "group": "gmane.other.group"}),  # not
    ])
    pf = _group_prefilter_bytes(["gmane.comp.example.devel"])
    records = list(iter_bulk_records(path, group_prefilter=pf))
    # The out-of-group record's body is long enough to hit the prefilter and
    # be skipped WITHOUT a full JSON parse; the in-group one must still come
    # through identically to the no-prefilter case.
    assert [u for u, _ in records] == ["urn:uuid:0001"]
    assert records[0][1]["group"] == "gmane.comp.example.devel"


def test_prefilter_short_lines_always_fall_through_to_full_parse(tmp_path):
    """Lines shorter than _MIN_LEN_FOR_PREFILTER must never be skipped via
    the byte check — they always get a full parse, so a genuine short
    action-like line can never be misclassified."""
    short_doc = {"group": "gmane.other.group", "lang": "en", "segments": [], "headers": {}}
    path = _write_corpus_file(tmp_path, [("urn:uuid:0003", short_doc)])
    pf = _group_prefilter_bytes(["gmane.comp.example.devel"])
    records = list(iter_bulk_records(path, group_prefilter=pf))
    # Falls through to full parse (too short for the prefilter fast path),
    # then record_in_scope (called separately by ingest()) would exclude it —
    # but iter_bulk_records itself always yields it since it only pre-filters,
    # never scope-filters.
    assert [u for u, _ in records] == ["urn:uuid:0003"]


# ── Fakes for Mongo / Redis, to test the batched ingest() flow end-to-end ────

class FakeBulkWriteResult:
    def __init__(self, upserted_ids):
        self.upserted_ids = upserted_ids


class FakeCollection:
    """Minimal in-memory stand-in for an AsyncIOMotorCollection."""

    def __init__(self):
        self.docs_by_urn: dict[str, dict] = {}
        self._next_id = 1
        self.bulk_write_calls = 0

    async def create_index(self, *args, **kwargs):
        return "urn_1"

    async def bulk_write(self, ops, ordered=False):
        self.bulk_write_calls += 1
        upserted = {}
        for i, op in enumerate(ops):
            # ops are UpdateOne instances in default (non-fresh-load) mode
            filt = op._filter
            update = op._doc["$set"]
            urn = filt["urn"]
            if urn in self.docs_by_urn:
                self.docs_by_urn[urn].update(update)
            else:
                new_id = f"oid-{self._next_id}"
                self._next_id += 1
                doc = {**update, "_id": new_id}
                self.docs_by_urn[urn] = doc
                upserted[i] = new_id
        return FakeBulkWriteResult(upserted)


class FakeBroker:
    def __init__(self):
        self.published: list[dict] = []

    async def publish_many(self, stream, events):
        self.published.extend(events)


@pytest.fixture
def patched_ingest(monkeypatch):
    fake_coll = FakeCollection()
    fake_broker = FakeBroker()

    class FakeDB(dict):
        def __getitem__(self, name):
            return fake_coll

    class FakeMongoClient:
        def __getitem__(self, name):
            return FakeDB()
        def close(self):
            pass

    import miner.gmane_ingester as gi
    monkeypatch.setattr(gi, "make_mongo_client", lambda: FakeMongoClient())

    async def _get_broker():
        return fake_broker
    monkeypatch.setattr(gi, "get_broker", _get_broker)

    return fake_coll, fake_broker


def test_ingest_batches_and_publishes_only_new_docs(tmp_path, patched_ingest):
    fake_coll, fake_broker = patched_ingest
    path = _write_corpus_file(tmp_path, [
        ("urn:uuid:A", EMAIL_DOC),
        ("urn:uuid:B", EMAIL_DOC),
        ("urn:uuid:C", EMAIL_DOC),
    ])
    from miner.gmane_ingester import ingest

    asyncio.run(ingest([path], groups=["gmane.comp.example.devel"], langs=["en"], batch_size=10))

    # All three should be new -> 3 pointer events published, one flush (batch < batch_size triggers only at finally-flush)
    assert len(fake_broker.published) == 3
    assert fake_coll.bulk_write_calls == 1  # one flush covers all 3 (under batch_size)
    assert len(fake_coll.docs_by_urn) == 3

    # Re-ingesting the SAME file must not re-publish (docs already exist) —
    # this is the "only publish for genuinely new docs" improvement.
    fake_broker.published.clear()
    asyncio.run(ingest([path], groups=["gmane.comp.example.devel"], langs=["en"], batch_size=10))
    assert fake_broker.published == []
    assert len(fake_coll.docs_by_urn) == 3  # no duplicates created


def test_ingest_respects_max(tmp_path, patched_ingest):
    fake_coll, fake_broker = patched_ingest
    path = _write_corpus_file(tmp_path, [
        ("urn:uuid:A", EMAIL_DOC),
        ("urn:uuid:B", EMAIL_DOC),
        ("urn:uuid:C", EMAIL_DOC),
    ])
    from miner.gmane_ingester import ingest
    asyncio.run(ingest([path], groups=["gmane.comp.example.devel"], max_records=2, batch_size=10))
    assert len(fake_coll.docs_by_urn) == 2
