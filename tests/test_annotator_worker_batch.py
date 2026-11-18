"""
Self-contained regression tests for the annotator worker's batch fault
tolerance and batched publishing (CHANGELOG 2026-08-20/2026-08-21).

Covers the batch behaviours added to `_annotate_batch`:

  1. Oversized TextUnits (len(text) > settings.annotate_max_chars) are skipped
     before the spaCy parse, so a pasted-log/stack-trace unit can never raise
     spaCy [E088] and kill the whole run. This is a scope decision, NOT signal
     filtering (AGENTS.md §5.3).
  2. If the shared `nlp.pipe` pass fails, annotation falls back to per-unit
     `nlp(text)` with individual try/except, so one bad unit degrades to a
     skip instead of halting the pipeline.
  3. Milestone B (2026-08-21): `_annotate_batch` is pure — it returns the
     serialised Signal payloads for the caller to flush in ONE publish_many,
     instead of awaiting one XADD per signal.

Deliberately service-free: a fake nlp (pipe/text), fake rule annotator, and
fake classifier stand in for spaCy + Redis/Neo4j.
Run: pytest tests/test_annotator_worker_batch.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any

from annotators.base import Signal, TextUnit
from annotators.worker import _annotate_batch, _signal_to_payload
from settings import settings


class FakeNlp:
    """Records what is parsed; pipe() can be made to raise."""

    def __init__(self) -> None:
        self.pipe_called = 0
        self.single_called = 0
        self.fail_pipe = False
        self.fail_texts: set[str] = set()

    def pipe(self, texts: list[str], **_: Any):
        self.pipe_called += 1
        if self.fail_pipe:
            raise RuntimeError("simulated nlp.pipe failure")
        return [f"doc-{t}" for t in texts]

    def __call__(self, text: str) -> str:
        self.single_called += 1
        if text in self.fail_texts:
            raise RuntimeError("simulated single-parse failure")
        return f"doc-{text}"


class FakeAnnotator:
    """Rule annotator that records (unit, doc) pairs and emits signals."""

    def __init__(self, name: str = "fake_rule") -> None:
        self.name = name
        self.seen: list[tuple[str, Any]] = []
        self.fail_unit_id: str | None = None
        self.emit = True

    def annotate(self, unit: TextUnit, doc: Any) -> list[Signal]:
        self.seen.append((unit.text_unit_id, doc))
        if self.fail_unit_id and unit.text_unit_id == self.fail_unit_id:
            raise RuntimeError("simulated annotator failure")
        if not self.emit:
            return []
        return [
            Signal(
                text_unit_id=unit.text_unit_id,
                layer="lexical",
                category="fixed_phrase",
                subcategory="blind_spot",
                surface_form="sure",
                span_start=0,
                span_end=4,
                rule_id="lex.fixed_phrase_test",
                rule_version="0.1",
            )
        ]


class FakeClassifier:
    """Classifier that records which TextUnits it is handed."""

    def __init__(self) -> None:
        self.seen_ids: list[str] = []
        self.emit = False

    def batch_annotate(self, units: list[TextUnit]) -> list[Signal]:
        self.seen_ids = [u.text_unit_id for u in units]
        if not self.emit:
            return []
        return [
            Signal(
                text_unit_id=u.text_unit_id,
                layer="classifier",
                category="roberta_binary",
                subcategory=None,
                surface_form="",
                span_start=0,
                span_end=len(u.text),
                rule_id="clf.roberta_binary",
                rule_version="0.1",
                confidence=0.9,
            )
            for u in units
        ]


def _unit(text_unit_id: str, text: str) -> TextUnit:
    return TextUnit(
        text_unit_id=text_unit_id,
        parent_id="jira:apache:TEST-1",
        parent_type="jira_issue",
        repo="jira:apache",
        parent_number=None,
        role="body",
        position=1,
        text=text,
        lang="en",
        token_count=len(text.split()),
        sha256="",
        author_login=None,
        created_at=None,
    )


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_oversized_unit_is_skipped_before_parse():
    nlp = FakeNlp()
    rule = FakeAnnotator()
    clf = FakeClassifier()
    units = [
        _unit("small", "I am not sure."),
        _unit("huge", "x" * (settings.annotate_max_chars + 1)),
    ]

    n_skipped, n_annotated, payloads, complete = _run(_annotate_batch(units, nlp, [rule], [clf]))

    assert n_skipped == 1
    assert n_annotated == 1
    assert complete is True
    # The oversized unit never reaches a rule annotator or the classifier.
    assert rule.seen == [("small", "doc-I am not sure.")]
    assert clf.seen_ids == ["small"]
    # The batch parse ran only on parseable texts.
    assert nlp.pipe_called == 1
    # One signal for the annotated unit, serialised to the stream shape.
    assert len(payloads) == 1
    assert payloads[0]["text_unit_id"] == "small"
    assert payloads[0]["rule_id"] == "lex.fixed_phrase_test"


def test_pipe_failure_falls_back_to_per_unit_parse():
    nlp = FakeNlp()
    nlp.fail_pipe = True
    rule = FakeAnnotator()
    clf = FakeClassifier()
    units = [_unit("a", "alpha"), _unit("b", "beta")]

    n_skipped, n_annotated, _payloads, complete = _run(_annotate_batch(units, nlp, [rule], [clf]))

    assert n_skipped == 0
    assert n_annotated == 2
    assert complete is True
    assert nlp.single_called == 2
    # All units were recovered via the per-unit fallback.
    assert [u for u, _ in rule.seen] == ["a", "b"]
    # Classifier input is length-sorted (padding fix): "beta" (4) before "alpha" (5).
    assert clf.seen_ids == ["b", "a"]


def test_per_unit_parse_failure_skips_only_that_unit():
    nlp = FakeNlp()
    nlp.fail_pipe = True
    nlp.fail_texts = {"beta"}
    rule = FakeAnnotator()
    clf = FakeClassifier()
    units = [_unit("a", "alpha"), _unit("b", "beta")]

    n_skipped, n_annotated, _payloads, complete = _run(_annotate_batch(units, nlp, [rule], [clf]))

    assert n_annotated == 1
    assert complete is False
    assert [u for u, _ in rule.seen] == ["a"]
    assert clf.seen_ids == ["a"]


def test_annotator_failure_is_isolated_within_batch():
    nlp = FakeNlp()
    rule = FakeAnnotator()
    rule.fail_unit_id = "a"
    clf = FakeClassifier()
    units = [_unit("a", "alpha"), _unit("b", "beta")]

    n_skipped, n_annotated, _payloads, complete = _run(_annotate_batch(units, nlp, [rule], [clf]))

    assert n_annotated == 2  # both parsed; the failing annotator logged, not raised
    assert complete is False  # the failed unit blocks the contiguous resume mark
    assert [u for u, _ in rule.seen] == ["a", "b"]
    # Classifier input is length-sorted (padding fix).
    assert clf.seen_ids == ["b", "a"]


def test_payloads_from_rule_and_classifier_are_all_returned():
    nlp = FakeNlp()
    rule = FakeAnnotator()
    clf = FakeClassifier()
    clf.emit = True
    units = [_unit("a", "alpha"), _unit("b", "beta")]

    _n_skipped, n_annotated, payloads, complete = _run(_annotate_batch(units, nlp, [rule], [clf]))

    assert n_annotated == 2
    assert complete is True
    # 2 rule signals + 2 classifier signals, all in one returned list.
    assert len(payloads) == 4
    ids = [p["text_unit_id"] for p in payloads]
    assert ids.count("a") == 2 and ids.count("b") == 2
    layers = {p["layer"] for p in payloads}
    assert layers == {"lexical", "classifier"}


def test_signal_to_payload_forwarding_shape():
    sig = Signal(
        text_unit_id="u1",
        layer="rhetorical",
        category="visibility",
        subcategory="blind_spot",
        surface_form="blinded",
        span_start=0,
        span_end=7,
        rule_id="rhet.visibility",
        rule_version="0.2",
        confidence=0.5,
        weight=1.0,
        status="active",
        payload={"note": "x"},
    )
    p = _signal_to_payload(sig)
    assert p["signal_id"] == sig.signal_id
    assert p["layer"] == "rhetorical"
    assert p["category"] == "visibility"
    assert p["subcategory"] == "blind_spot"
    assert p["weight"] == 1.0
    assert p["status"] == "active"
    assert p["payload"] == {"note": "x"}
