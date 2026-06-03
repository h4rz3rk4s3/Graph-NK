"""
Throttled progress logging for pipeline workers.

Emits "done / total (pct) | rate | elapsed | ETA" at most once every
`log_every_sec` seconds so long phases report steadily without flooding the log.

Two modes:
  - Fixed total (e.g. count of TextUnits, XLEN of an untrimmed stream): pass
    `total=` at construction. Shows percentage and ETA to completion.
  - Live queue (e.g. a stream still being produced and trimmed as consumed):
    pass `remaining=` to maybe_log() each time. Shows done + queued + ETA to
    drain the current queue. The queue may grow while the producer is active;
    the ETA converges once production stops.

See CHANGELOG 2026-06-03.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger("progress")


def _fmt(seconds: float | None) -> str:
    """Format a duration as H:MM:SS (or M:SS under an hour). None → em dash."""
    if seconds is None:
        return "—"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


class Progress:
    """Accumulate processed counts and log progress on a time throttle."""

    def __init__(self, label: str, total: int | None = None, log_every_sec: float = 5.0):
        self.label = label
        self.total = total
        self.done = 0
        self._start = time.monotonic()
        self._last = 0.0  # force the first maybe_log to emit
        self._every = log_every_sec
        if total is not None:
            logger.info("%s — starting: %d to process", label, total)
        else:
            logger.info("%s — starting", label)

    def add(self, n: int = 1) -> None:
        self.done += n

    def maybe_log(self, remaining: int | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last) < self._every:
            return
        self._last = now
        elapsed = now - self._start
        rate = self.done / elapsed if elapsed > 0 else 0.0

        if self.total is not None:
            # Fixed-total mode: percentage + ETA to completion.
            rem = max(self.total - self.done, 0)
            pct = (100.0 * self.done / self.total) if self.total else 100.0
            eta = (rem / rate) if rate > 0 else None
            logger.info(
                "%-18s %7d/%-7d (%4.1f%%) | %5.0f/s | elapsed %s | ETA %s",
                self.label, self.done, self.total, pct, rate, _fmt(elapsed), _fmt(eta),
            )
        elif remaining is not None:
            # Live-queue mode: done + queued + ETA to drain current queue.
            eta = (remaining / rate) if rate > 0 else None
            logger.info(
                "%-18s %7d done | %6d queued | %5.0f/s | elapsed %s | ETA %s",
                self.label, self.done, remaining, rate, _fmt(elapsed), _fmt(eta),
            )
        else:
            logger.info(
                "%-18s %7d done | %5.0f/s | elapsed %s",
                self.label, self.done, rate, _fmt(elapsed),
            )

    def finish(self) -> None:
        elapsed = time.monotonic() - self._start
        rate = self.done / elapsed if elapsed > 0 else 0.0
        logger.info(
            "%-18s complete: %d processed in %s (%.0f/s)",
            self.label, self.done, _fmt(elapsed), rate,
        )
