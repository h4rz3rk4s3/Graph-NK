"""
Self-contained tests for Stage-2 concurrency machinery (CHANGELOG 2026-08-21):

  - `_shard_where`: disjoint [id_lo, id_hi) range clauses appended to an
    existing scope WHERE — the correctness core of sharded annotation.
  - `_wait_for_backlog`: the annotator-side backpressure gate that stops a fast
    producer from filling Redis while the projector drains behind it.
  - `broker.read_all` producer-aware exit (`stop_event`): the Phase-2 projector
    must NOT exit on stream silence while producers are alive — the
    2026-08-18 premature-exit class of bug — and must exit promptly once all
    producers are done and the stream is drained.
  - `_wait_for_children_or_projector`: the parent's poll loop must return when
    the projector task finishes even if annotator children are still alive — the
    2026-08-21 projector-death hang fix.

All service-free (fake broker/redis). Run: pytest tests/test_annotator_sharding.py -v
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from annotators.worker import _quantile_boundaries, _shard_where, _wait_for_backlog
from scripts.run_pipeline import _wait_for_children_or_projector
from settings import settings


def test_shard_where_no_bounds_leaves_where_untouched():
    where = "WHERE (u.lang IN $langs OR u.lang IS NULL)"
    params = {"langs": ["en"]}
    out_where, out_params = _shard_where(where, dict(params), None, None)
    assert out_where == where
    assert out_params == params


def test_shard_where_lo_only_appends_to_existing_where():
    where = "WHERE (u.lang IN $langs OR u.lang IS NULL)"
    params = {"langs": ["en"]}
    out_where, out_params = _shard_where(where, dict(params), "b1", None)
    assert out_where == ("WHERE (u.lang IN $langs OR u.lang IS NULL) AND u.id >= $id_lo")
    assert out_params["id_lo"] == "b1"
    assert out_params["langs"] == ["en"]


def test_shard_where_hi_only_on_empty_where():
    out_where, out_params = _shard_where("", {}, None, "b1")
    assert out_where == "WHERE u.id < $id_hi"
    assert out_params == {"id_hi": "b1"}


def test_shard_where_both_bounds_on_empty_where():
    out_where, out_params = _shard_where("", {}, "b0", "b1")
    assert out_where == "WHERE u.id >= $id_lo AND u.id < $id_hi"
    assert out_params == {"id_lo": "b0", "id_hi": "b1"}


# ── _quantile_boundaries (token-balanced shard split) ────────────────────────


def test_quantile_boundaries_split_by_token_cumulative_sum():
    # 12 rows of 1 token each, 3 shards → boundaries at cumulative 4 and 8.
    rows = [(f"u{i}", 1) for i in range(12)]
    boundaries = _quantile_boundaries(total_tokens=12, shards=3, rows=rows)
    assert boundaries == ["u4", "u8"]


def test_quantile_boundaries_balance_work_not_node_count():
    # Uneven tokens: the boundary falls where cumulative tokens reach the
    # quantile, not at a fixed index. total=10, shards=2 → boundary at cum 5.
    rows = [("u0", 4), ("u1", 3), ("u2", 2), ("u3", 1)]
    boundaries = _quantile_boundaries(total_tokens=10, shards=2, rows=rows)
    assert boundaries == ["u1"]  # cum crosses 5 at u1 (4+3)


def test_quantile_boundaries_raises_if_scan_does_not_cross_all_thresholds():
    rows = [("u0", 1), ("u1", 1)]
    with pytest.raises(RuntimeError):
        _quantile_boundaries(total_tokens=100, shards=4, rows=rows)


class _FakeRedis:
    """Minimal fake redis.asyncio client: xlen only."""

    def __init__(self, length: int) -> None:
        self._len = length

    async def xlen(self, stream: str) -> int:
        return self._len


class _FakeBroker:
    def __init__(self, length: int) -> None:
        self._client = _FakeRedis(length)

    async def stream_length(self, stream: str) -> int:
        return await self._client.xlen(stream)


def test_backlog_pauses_until_drain():
    settings.annotator_max_stream_signals_backlog = 100

    class GrowingBroker(_FakeBroker):
        def __init__(self) -> None:
            super().__init__(101)  # starts over the ceiling
            self.checks = 0

        async def stream_length(self, stream: str) -> int:
            self.checks += 1
            if self.checks >= 3:
                self._client._len = 50  # projector caught up
            return await super().stream_length(stream)

    async def _run() -> None:
        await _wait_for_backlog(GrowingBroker())

    asyncio.run(_run())
    # It polled (>=3 times) and returned once the drain dropped the backlog.


def test_backlog_returns_immediately_below_ceiling():
    settings.annotator_max_stream_signals_backlog = 100

    class QuietBroker(_FakeBroker):
        def __init__(self) -> None:
            super().__init__(50)

    async def _run() -> None:
        await _wait_for_backlog(QuietBroker())

    asyncio.run(_run())  # no hang; returns straight away


def test_backlog_disabled_when_ceiling_zero():
    settings.annotator_max_stream_signals_backlog = 0

    async def _run() -> None:
        await _wait_for_backlog(_FakeBroker(10**9))

    asyncio.run(_run())  # gate disabled: returns despite huge backlog


# ── broker.read_all producer-aware exit ──────────────────────────────────────


class _FakeReadRedis:
    """Fake redis client for read_all: scripted xread results + xlen + xdel."""

    def __init__(self, rounds: list[Any]) -> None:
        self.rounds = rounds
        self.round_idx = 0
        self.deleted: list[Any] = []

    async def xread(self, streams: dict, count: int, block: int) -> list[Any]:
        # Simulate the real redis block: real xread suspends on I/O, so other
        # tasks get scheduled; a fake that returns instantly would let read_all's
        # idle loop busy-spin the event loop and starve the other tasks.
        await asyncio.sleep(0.005)
        if self.round_idx >= len(self.rounds):
            return []
        r = self.rounds[self.round_idx]
        self.round_idx += 1
        return r

    async def xlen(self, stream: str) -> int:
        return 0

    async def xdel(self, stream: str, *ids: Any) -> None:
        self.deleted.extend(ids)


def _msg(stream: str, msg_id: str, payload: str) -> list[Any]:
    return [(stream, [(msg_id, {b"payload": payload.encode()})])]


class _FakeReadBroker:
    def __init__(self, redis: _FakeReadRedis) -> None:
        self._client = redis
        self._stream = "graphrag.signals"

    async def stream_length(self, stream: str) -> int:
        return await self._client.xlen(stream)

    async def read_all(self, stream: str, **kwargs: Any):
        from broker import RedisBroker  # reuse the real method, fake client

        async for batch in RedisBroker.read_all(self, stream, **kwargs):
            yield batch


class _MalformedRedis(_FakeReadRedis):
    """One malformed stream entry; xlen reflects untrimmed entries so the
    stop_event exit condition (stream drained) is only satisfiable once the bad
    ID is actually XDEL'd."""

    def __init__(self, round_data: list[Any], n_entries: int) -> None:
        super().__init__(round_data)
        self._n_entries = n_entries

    async def xlen(self, stream: str) -> int:
        # Non-zero until the entry is trimmed; zero once read_all XDEL's it.
        return 0 if len(self.deleted) >= self._n_entries else self._n_entries


def test_read_all_trims_all_malformed_batch_so_stream_drains():
    # One batch whose EVERY payload is malformed: read_all must still consume
    # (trim) its ID, or XLEN stays nonzero and the producer-aware consumer hangs
    # forever waiting for a stream that will never drain.
    malformed = _msg("s", "g-1", "not-json{{{")
    # rounds is a list of rounds, each a list of (stream, messages) — so wrap
    # the single malformed round in another list (same shape as _FakeReadRedis).
    redis = _MalformedRedis([malformed], n_entries=1)

    async def _driver() -> list[Any]:
        stop_event = asyncio.Event()
        stop_event.set()  # producers done; nothing else queued
        out: list[dict] = []
        async for batch in _FakeReadBroker(redis).read_all(
            "s", batch_size=10, block_ms=10, trim=True, stop_event=stop_event
        ):
            out.extend(batch)
        return out

    result = asyncio.run(_driver())
    assert result == []
    assert "g-1" in redis.deleted


async def _collect_read_all(broker: Any, stop_event: asyncio.Event | None):
    out: list[dict[str, Any]] = []
    async for batch in broker.read_all(
        "s", batch_size=10, block_ms=10, trim=True, stop_event=stop_event
    ):
        out.extend(batch)
    return out


def test_read_all_keeps_waiting_then_exits_when_producers_done():
    # Producers are alive for a long stretch of stream silence (several idle
    # rounds of 10ms). read_all must NOT exit during that silence; once the
    # producers signal completion it drains the tail and exits.
    redis = _FakeReadRedis(
        [
            _msg("s", "1-1", '{"a":1}'),
            [],  # idle round 1
            [],  # idle round 2
            [],  # idle round 3
            _msg("s", "2-1", '{"b":2}'),
        ]
    )

    async def _collect(stop_event: asyncio.Event, out: list[dict[str, Any]]):
        async for batch in _FakeReadBroker(redis).read_all(
            "s", batch_size=10, block_ms=10, trim=True, stop_event=stop_event
        ):
            out.extend(batch)

    async def _driver() -> None:
        stop_event = asyncio.Event()  # producers still alive
        out: list[dict[str, Any]] = []
        task = asyncio.create_task(_collect(stop_event, out))
        await asyncio.sleep(0.2)
        # Several idle rounds passed with producers alive → must still be running.
        assert not task.done(), "read_all exited prematurely during producer silence"
        stop_event.set()  # producers finished
        await asyncio.wait_for(task, timeout=5)
        assert out == [{"a": 1}, {"b": 2}]

    asyncio.run(_driver())


def test_read_all_exits_when_producers_done_and_stream_drained():
    # Producers signal completion AND stream empty → exit promptly.
    redis = _FakeReadRedis([_msg("s", "1-1", '{"a":1}')])

    async def _driver() -> None:
        stop_event = asyncio.Event()
        stop_event.set()  # producers done; nothing left in stream
        result = await asyncio.wait_for(
            _collect_read_all(_FakeReadBroker(redis), stop_event), timeout=5
        )
        assert result == [{"a": 1}]

    asyncio.run(_driver())


def test_read_all_without_stop_event_keeps_legacy_exit():
    # Legacy mode (stop_event=None): two idle rounds still exit — used by
    # --skip-annotate standalone drains.
    redis = _FakeReadRedis(
        [
            _msg("s", "1-1", '{"a":1}'),
            [],
            [],
        ]
    )

    async def _driver() -> None:
        result = await _collect_read_all(_FakeReadBroker(redis), None)
        assert result == [{"a": 1}]


# ── parent poll loop (projector-death hang fix) ──────────────────────────────


class _FakeProc:
    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def test_poll_returns_projector_when_projector_dies_despite_alive_children():
    # Regression for the 2026-08-21 hang: children stay alive (they would block
    # forever on backpressure once nothing drains), but the projector task fails.
    # The poll must return "projector" promptly instead of polling the
    # never-exiting children forever.
    children = [(0, _FakeProc(True)), (1, _FakeProc(True))]

    async def _failing_projector() -> None:
        raise RuntimeError("projector down")

    async def _driver() -> str:
        task = asyncio.create_task(_failing_projector())
        await asyncio.sleep(0.01)  # let the task finish (done with exception)
        return await asyncio.wait_for(_wait_for_children_or_projector(children, task), timeout=5)

    assert asyncio.run(_driver()) == "projector"


def test_poll_returns_children_when_children_exit_first():
    children = [(0, _FakeProc(False)), (1, _FakeProc(False))]

    async def _long_projector() -> None:
        await asyncio.sleep(60)

    async def _driver() -> str:
        task = asyncio.create_task(_long_projector())
        result = await asyncio.wait_for(_wait_for_children_or_projector(children, task), timeout=5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return result

    assert asyncio.run(_driver()) == "children"

    asyncio.run(_driver())
