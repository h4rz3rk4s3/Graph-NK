"""
Self-contained tests for incremental Stage 2 (`--only-unannotated`,
CHANGELOG 2026-08-27):

  - `_scope_filter(only_unannotated=True)`: adds the NOT EXISTS CLASSIFIED_AS
    predicate and the oversized-size guard; the default full-run scope does not.
  - `_hwm_key`: incremental and full-run checkpoints are distinct (an
    incremental run can never clobber a full-run HWM for the same bounds).
  - `_validate_incremental_flags`: rejects every combination of
    --only-unannotated with --resume / --resume-from / --shard-index /
    --skip-annotate.
  - projector `upsert_signals_batch`: the ClassifierVerdict / CLASSIFIED_AS
    completion marker is written LAST, after the plain signals and their
    MATCHES_MARKER / INSTANTIATES wiring.

All service-free (fake neo4j driver / argparse Namespace). Run:
pytest tests/test_incremental_annotation.py -v
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import Any

import pytest

from annotators.worker import _hwm_key, _scope_filter
from projector.graph_projector import GraphProjector
from scripts.run_pipeline import _run_annotate_and_project, _validate_incremental_flags
from settings import settings

# ── _scope_filter incremental vs full ────────────────────────────────────────


def test_scope_filter_default_has_no_incremental_predicates():
    where, _params = _scope_filter()
    assert "CLASSIFIED_AS" not in where
    assert "max_chars" not in where


def test_scope_filter_incremental_adds_verdict_and_size_guard():
    where, params = _scope_filter(only_unannotated=True)
    assert "NOT EXISTS { MATCH (u)-[:CLASSIFIED_AS]->() }" in where
    assert "size(u.text) <= $max_chars" in where
    assert params["max_chars"] == settings.annotate_max_chars


def test_scope_filter_incremental_disabled_excludes_predicates():
    where, params = _scope_filter(only_unannotated=False)
    assert "NOT EXISTS" not in where
    assert "max_chars" not in params


# ── _hwm_key separation between incremental and full run ────────────────────


def test_hwm_key_distinguishes_incremental_scope():
    full = _hwm_key("lo", "hi", only_unannotated=False)
    inc = _hwm_key("lo", "hi", only_unannotated=True)
    assert full != inc
    assert inc == _hwm_key("lo", "hi", only_unannotated=True)  # deterministic


# ── CLI option-combination validation ───────────────────────────────────────


def _ns(**kwargs: Any) -> argparse.Namespace:
    defaults = {
        "resume": False,
        "resume_from": None,
        "shard_index": None,
        "skip_annotate": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def test_incremental_flags_reject_resume():
    with pytest.raises(SystemExit):
        _validate_incremental_flags(_ns(resume=True))


def test_incremental_flags_reject_resume_from():
    with pytest.raises(SystemExit):
        _validate_incremental_flags(_ns(resume_from="some:id"))


def test_incremental_flags_reject_shard_index():
    with pytest.raises(SystemExit):
        _validate_incremental_flags(_ns(shard_index=2))


def test_incremental_flags_reject_skip_annotate():
    with pytest.raises(SystemExit):
        _validate_incremental_flags(_ns(skip_annotate=True))


def test_incremental_flags_accept_clean_args():
    _validate_incremental_flags(_ns())  # no exception


# ── projector completion-marker ordering ────────────────────────────────────


class _RecSession:
    def __init__(self, fail_on: Any, log: list[str]) -> None:
        self._fail_on = fail_on
        self._log = log

    async def run(self, cypher: str, **_: Any) -> Any:
        self._log.append(cypher)
        if self._fail_on is not None and self._fail_on(cypher):
            raise RuntimeError("simulated projector failure")
        return None


class _RecSessionCtx:
    def __init__(self, fail_on: Any, log: list[str]) -> None:
        self._fail_on = fail_on
        self._log = log

    async def __aenter__(self) -> _RecSession:
        return _RecSession(self._fail_on, self._log)

    async def __aexit__(self, *_: Any) -> None:
        return None


class _RecDriver:
    def __init__(self, fail_on: Any = None) -> None:
        self.log: list[str] = []
        self._fail_on = fail_on

    def session(self) -> _RecSessionCtx:
        return _RecSessionCtx(self._fail_on, self.log)


def _plain_signal(unit_id: str, layer: str) -> dict[str, Any]:
    return {
        "signal_id": f"{unit_id}:{layer}",
        "text_unit_id": unit_id,
        "layer": layer,
        "category": "fixed_phrase" if layer == "lexical" else "metaphor",
        "subcategory": "x",
        "surface_form": "x",
        "span_start": 0,
        "span_end": 1,
        "rule_id": "test",
        "rule_version": "0.1",
        "confidence": 0.9,
        "weight": 1.0,
        "status": "active",
        "payload": {
            "lemma": "x",
            "lexicon_version": "v0.2",
            "pos": "VERB",
            "polarity": "neutral",
            "source_citation": "test",
        },
    }


def _verdict_signal(unit_id: str) -> dict[str, Any]:
    return {
        "signal_id": f"{unit_id}:clf:verdict",
        "text_unit_id": unit_id,
        "layer": "classifier",
        "category": "roberta_binary",
        "subcategory": None,
        "surface_form": "",
        "span_start": 0,
        "span_end": 1,
        "rule_id": "clf.roberta_binary",
        "rule_version": "0.1",
        "confidence": 0.9,
        "weight": 1.0,
        "status": "active",
        "payload": {
            "label": 1,
            "model_id": "m",
            "model_version": "v",
            "__verdict__": True,
        },
    }


def test_upsert_signals_batch_writes_verdict_last():
    drv = _RecDriver()
    proj = GraphProjector(drv)  # type: ignore[arg-type]
    batch = [
        _plain_signal("u1", "lexical"),
        _plain_signal("u1", "rhetorical"),
        _verdict_signal("u1"),
    ]
    asyncio.run(proj.upsert_signals_batch(batch))
    qs = drv.log
    # A plain-signal MERGE, the lexical wiring, the rhetorical wiring, and the
    # verdict MERGE must ALL be present.
    assert len(qs) == 4
    assert any("MERGE (sig:Signal" in q for q in qs)
    assert any("MATCHES_MARKER" in q for q in qs)
    assert any("INSTANTIATES" in q for q in qs)
    verdict_idx = next(i for i, q in enumerate(qs) if "ClassifierVerdict" in q)
    # The verdict (completion marker) is the LAST transaction.
    assert verdict_idx == len(qs) - 1


def test_upsert_signals_batch_verdict_only_writes_verdict():
    drv = _RecDriver()
    proj = GraphProjector(drv)  # type: ignore[arg-type]
    asyncio.run(proj.upsert_signals_batch([_verdict_signal("u1")]))
    qs = drv.log
    assert len(qs) == 1
    assert "ClassifierVerdict" in qs[0]


@pytest.mark.parametrize(
    "fail_on",
    [
        # Plain-signal MERGE fails.
        lambda q: "MERGE (sig:Signal" in q,
        # Lexical wiring fails.
        lambda q: "MATCHES_MARKER" in q,
        # Rhetorical wiring fails.
        lambda q: "INSTANTIATES" in q,
    ],
)
def test_verdict_not_written_when_any_prior_transaction_fails(fail_on):
    # If any plain-signal / wiring transaction fails, the ClassifierVerdict
    # (completion marker) must NEVER be attempted — otherwise the unit is
    # marked complete while its signals are partial (CHANGELOG 2026-08-27).
    drv = _RecDriver(fail_on=fail_on)
    proj = GraphProjector(drv)  # type: ignore[arg-type]
    batch = [
        _plain_signal("u1", "lexical"),
        _plain_signal("u1", "rhetorical"),
        _verdict_signal("u1"),
    ]
    with pytest.raises(RuntimeError):
        asyncio.run(proj.upsert_signals_batch(batch))
    assert not any("ClassifierVerdict" in q for q in drv.log)
    assert not any("CLASSIFIED_AS" in q for q in drv.log)


# ── orchestration: zero-work drain, shard reduction, incremental wiring ──────


class _FakeProc:
    def __init__(self) -> None:
        self.exitcode = 0

    def start(self) -> None:
        self.started = True

    def is_alive(self) -> bool:
        return False

    def terminate(self) -> None:
        pass

    def join(self) -> None:
        pass


class _FakeCtx:
    def __init__(self) -> None:
        self.spawned: list[tuple[Any, Any, str]] = []

    def Process(self, target: Any, args: Any, name: str) -> _FakeProc:
        self.spawned.append((target, args, name))
        return _FakeProc()


class _FakeMP:
    def __init__(self) -> None:
        self.ctx = _FakeCtx()

    def get_context(self, method: str) -> _FakeCtx:
        return self.ctx


def test_zero_remaining_units_drains_without_spawning(monkeypatch):
    async def fake_count(**_: Any) -> int:
        return 0

    drained = {"called": False}

    async def fake_drain(_stop_event: Any = None) -> None:
        drained["called"] = True

    monkeypatch.setattr("annotators.worker.count_in_scope", fake_count)
    monkeypatch.setattr("projector.worker.run_projector_stage2", fake_drain)

    asyncio.run(_run_annotate_and_project(8, None, only_unannotated=True))
    assert drained["called"] is True


def test_fewer_units_than_shards_reduces_to_one_shard(monkeypatch):
    async def fake_count(**_: Any) -> int:
        return 3

    async def fake_drain(_stop_event: Any = None) -> None:
        pass

    monkeypatch.setattr("annotators.worker.count_in_scope", fake_count)
    monkeypatch.setattr("projector.worker.run_projector_stage2", fake_drain)
    mp = _FakeMP()
    monkeypatch.setitem(sys.modules, "multiprocessing", mp)

    asyncio.run(_run_annotate_and_project(8, None, only_unannotated=True))
    # Reduced to a single shard → exactly one annotator spawned.
    assert len(mp.ctx.spawned) == 1
    target, args, _name = mp.ctx.spawned[0]
    assert args[1] == 1  # shards reduced to 1
    assert args[6] is True  # only_unannotated forwarded to the child


def test_incremental_forwards_mode_to_boundaries_and_children(monkeypatch):
    async def count(**_: Any) -> int:
        return 100

    async def drain(_stop_event: Any = None) -> None:
        pass

    recorded: dict[str, Any] = {}

    async def fake_boundaries(shards: int, id_lo: Any = None, only_unannotated: bool = False):
        recorded["shards"] = shards
        recorded["id_lo"] = id_lo
        recorded["only_unannotated"] = only_unannotated
        return ["b1"]

    monkeypatch.setattr("annotators.worker.count_in_scope", count)
    monkeypatch.setattr("projector.worker.run_projector_stage2", drain)
    monkeypatch.setattr("annotators.worker.compute_shard_boundaries", fake_boundaries)
    mp = _FakeMP()
    monkeypatch.setitem(sys.modules, "multiprocessing", mp)

    asyncio.run(_run_annotate_and_project(2, None, only_unannotated=True))
    assert recorded == {"shards": 2, "id_lo": None, "only_unannotated": True}
    # Two spawned shards, both carrying only_unannotated=True to the child.
    assert len(mp.ctx.spawned) == 2
    assert all(args[6] is True for _t, args, _n in mp.ctx.spawned)
