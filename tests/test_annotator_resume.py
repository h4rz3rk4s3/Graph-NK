"""
Self-contained tests for Stage-2 resume machinery (CHANGELOG 2026-08-23):

  - `_hwm_key`: a collision-proof, config-scoped Redis key for one shard range.
  - `_iter_text_units` `start_id`: the resumed walk begins INCLUSIVE at the
    boundary id (re-doing it is safe — Signal MERGEs are idempotent) and
    switches to exclusive keyset pagination on subsequent pages.
  - `_annotate_batch` completeness: a batch with a parse/annotator/classifier
    failure returns `complete=False` so the worker stops without advancing the
    contiguous resume mark (the failed batch must be retried, not skipped).
  - `_classifier_unit_batches`: the padding fix sorts + splits the parsed units
    into length-homogeneous microbatches so a long text does not pad its
    neighbours; every unit is still classified exactly once.

All service-free (fake neo4j driver / fake annotators).
Run: pytest tests/test_annotator_resume.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any

from annotators.worker import (
    _annotate_batch,
    _classifier_unit_batches,
    _hwm_key,
    _iter_text_units,
)
from settings import settings

# ── _hwm_key ─────────────────────────────────────────────────────────────────


def test_hwm_key_is_deterministic_for_same_bounds():
    assert _hwm_key("a", "b") == _hwm_key("a", "b")


def test_hwm_key_ignores_colon_collisions_between_bounds():
    # "a:b","c" vs "a","b:c" must NOT collide (ids contain colons).
    assert _hwm_key("a:b", "c") != _hwm_key("a", "b:c")


def test_hwm_key_scopes_to_annotation_config():
    key_default = _hwm_key("lo", "hi")
    old = settings.annotate_min_tokens
    try:
        settings.annotate_min_tokens = 99
        assert _hwm_key("lo", "hi") != key_default
    finally:
        settings.annotate_min_tokens = old


def test_hwm_key_starts_with_configured_prefix():
    assert _hwm_key(None, None).startswith(settings.annotate_hwm_key_prefix + ":")


# ── _iter_text_units start_id (resume boundary) ──────────────────────────────


class _FakeResult:
    """Async-iterable of record dicts (mimics a neo4j query Result)."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def __aiter__(self) -> _FakeResult:
        self._it = iter(self._rows)
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._it)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class _FakeSession:
    def __init__(self, driver: _FakeDriver) -> None:
        self.driver = driver

    async def run(self, query: str, **params: Any) -> _FakeResult:
        self.driver.queries.append((query, params))
        rows = self.driver.script.pop(0) if self.driver.script else []
        return _FakeResult(rows)


class _FakeSessionCtx:
    def __init__(self, driver: _FakeDriver) -> None:
        self.driver = driver

    async def __aenter__(self) -> _FakeSession:
        return _FakeSession(self.driver)

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _FakeDriver:
    def __init__(self, script: list[list[dict[str, Any]]]) -> None:
        self.script = script
        self.queries: list[tuple[str, dict[str, Any]]] = []

    def session(self) -> _FakeSessionCtx:
        return _FakeSessionCtx(self)


def _row(tu_id: str) -> dict[str, Any]:
    return {"id": tu_id, "text": "t", "parent_type": "jira_issue"}


def test_iter_text_units_starts_inclusive_at_resume_boundary():
    # Page 1 must use `u.id >= $last_id`; page 2 must use `u.id > $last_id`.
    driver = _FakeDriver(
        [
            [_row("u1"), _row("u2")],
            [_row("u3")],
            [],
        ]
    )

    async def _collect() -> list[str]:
        ids: list[str] = []
        async for unit in _iter_text_units(
            driver, "WHERE u.parent_type = $pt", {"pt": "jira"}, page_size=2, start_id="u1"
        ):
            ids.append(unit.text_unit_id)
        return ids

    assert asyncio.run(_collect()) == ["u1", "u2", "u3"]
    q0 = driver.queries[0][0]
    q1 = driver.queries[1][0]
    assert "u.id >= $last_id" in q0
    assert "u.id > $last_id" in q1
    assert driver.queries[0][1]["last_id"] == "u1"
    assert driver.queries[1][1]["last_id"] == "u2"


def test_iterate_without_start_id_is_exclusive_from_scratch():
    driver = _FakeDriver([[_row("u1")], []])

    async def _collect() -> list[str]:
        ids: list[str] = []
        async for unit in _iter_text_units(driver, "", {}, page_size=2):
            ids.append(unit.text_unit_id)
        return ids

    assert asyncio.run(_collect()) == ["u1"]
    assert "u.id > $last_id" in driver.queries[0][0]
    assert driver.queries[0][1]["last_id"] == ""


# ── _classifier_unit_batches (padding fix) ───────────────────────────────────


class _FakeNlp:
    def pipe(self, texts: list[str], **_: Any):
        return [f"doc-{t}" for t in texts]


class _EmitAll:
    """Rule annotator that emits one signal per unit regardless of content."""

    name = "fake_rule"
    version = "0.1"

    def annotate(self, unit: Any, doc: Any) -> list[Any]:
        from annotators.base import Signal

        return [
            Signal(
                text_unit_id=unit.text_unit_id,
                layer="lexical",
                category="fixed_phrase",
                subcategory="x",
                surface_form="x",
                span_start=0,
                span_end=1,
                rule_id="lex.test",
                rule_version="0.1",
            )
        ]


class _RecordingClassifier:
    """Classifier that records every (unit_id, batch_call) it receives."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def batch_annotate(self, units: list[Any]) -> list[Any]:
        from annotators.base import Signal

        self.calls.append([u.text_unit_id for u in units])
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


def _unit(text_unit_id: str, text: str) -> Any:
    from annotators.base import TextUnit

    return TextUnit(
        text_unit_id=text_unit_id,
        parent_id="p",
        parent_type="jira_issue",
        repo="r",
        parent_number=None,
        role="body",
        position=0,
        text=text,
        lang="en",
        token_count=len(text.split()),
        sha256="",
        author_login=None,
        created_at=None,
    )


def test_classifier_unit_batches_splits_into_length_homogeneous_groups():
    try:
        settings.classifier_batch_size = 2
        units = [
            _unit("long", "x" * 50),
            _unit("short", "x" * 2),
            _unit("mid", "x" * 20),
            _unit("tiny", "x"),
        ]
        batches = _classifier_unit_batches(units)
        # Each group is length-sorted and split at the configured size.
        assert [len(b) for b in batches] == [2, 2]
        assert [[u.text_unit_id for u in b] for b in batches] == [
            ["tiny", "short"],
            ["mid", "long"],
        ]
        # Every unit appears exactly once across all batches.
        flat = [u.text_unit_id for b in batches for u in b]
        assert sorted(flat) == sorted(u.text_unit_id for u in units)
    finally:
        settings.classifier_batch_size = 64


def test_classifier_splits_into_microbatches_and_covers_all_units():
    try:
        settings.classifier_batch_size = 2
        units = [_unit("long", "x" * 50), _unit("short", "x" * 2), _unit("mid", "x" * 20)]
        clf = _RecordingClassifier()
        _n, _annotated, payloads, complete = asyncio.run(
            _annotate_batch(units, _FakeNlp(), [_EmitAll()], [clf])
        )
        assert complete is True
        # Two classifier calls (microbatches of size 2), length-sorted.
        assert clf.calls == [["short", "mid"], ["long"]]
        # Every unit still classified exactly once: 3 rule + 3 classifier.
        ids = [p["text_unit_id"] for p in payloads]
        assert ids.count("short") == 2 and ids.count("mid") == 2 and ids.count("long") == 2
    finally:
        settings.classifier_batch_size = 64


# ── _annotate_batch completeness flag (do-not-advance-HWM on failure) ────────


class _Fake:
    """nlp fake; `fail_texts` marks per-unit parse failures."""

    def __init__(self) -> None:
        self.fail_pipe = False
        self.fail_texts: set[str] = set()

    def pipe(self, texts: list[str], **_: Any):
        if self.fail_pipe:
            raise RuntimeError("pipe down")
        return [f"doc-{t}" for t in texts]

    def __call__(self, text: str) -> str:
        if text in self.fail_texts:
            raise RuntimeError("single parse down")
        return f"doc-{text}"


class _FailOnUnit:
    """Rule annotator that raises for one specific unit id."""

    name = "fake_rule"
    version = "0.1"

    def __init__(self, fail_id: str | None = None) -> None:
        self.fail_id = fail_id

    def annotate(self, unit: Any, doc: Any) -> list[Any]:
        from annotators.base import Signal

        if unit.text_unit_id == self.fail_id:
            raise RuntimeError("annotator down")
        return [
            Signal(
                text_unit_id=unit.text_unit_id,
                layer="lexical",
                category="c",
                subcategory=None,
                surface_form="s",
                span_start=0,
                span_end=1,
                rule_id="lex.f",
                rule_version="0.1",
            )
        ]


class _FailClassifier:
    """Classifier that raises on a given call count."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        self.calls = 0
        self.fail_on_call = fail_on_call

    def batch_annotate(self, units: list[Any]) -> list[Any]:
        from annotators.base import Signal

        self.calls += 1
        if self.fail_on_call == self.calls:
            raise RuntimeError("classifier down")
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


def test_annotate_batch_returns_complete_false_on_per_unit_parse_failure():
    nlp = _Fake()
    nlp.fail_pipe = True
    nlp.fail_texts = {"beta"}
    _n, _a, _p, complete = asyncio.run(
        _annotate_batch([_unit("a", "alpha"), _unit("b", "beta")], nlp, [_EmitAll()], [])
    )
    assert complete is False


def test_annotate_batch_returns_complete_false_on_rule_failure():
    _n, _a, _s, complete = asyncio.run(
        _annotate_batch(
            [_unit("a", "alpha"), _unit("b", "beta")], _Fake(), [_FailOnUnit(fail_id="b")], []
        )
    )
    assert complete is False


def test_annotate_batch_returns_complete_false_on_classifier_failure():
    _n, _a, _s, complete = asyncio.run(
        _annotate_batch([_unit("a", "alpha")], _Fake(), [_EmitAll()], [_FailClassifier(1)])
    )
    assert complete is False


def test_annotate_batch_complete_true_on_clean_run():
    _n, _a, _s, complete = asyncio.run(
        _annotate_batch([_unit("a", "alpha"), _unit("b", "beta")], _Fake(), [_EmitAll()], [])
    )
    assert complete is True
