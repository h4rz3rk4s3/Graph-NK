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
from collections import deque

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

    def __init__(
        self,
        label: str,
        total: int | None = None,
        log_every_sec: float = 5.0,
        window_sec: float = 60.0,
    ):
        self.label = label
        self.total = total
        self.done = 0
        self._start = time.monotonic()
        self._last = 0.0  # force the first maybe_log to emit
        self._every = log_every_sec
        # True ROLLING window for the recent rate (CHANGELOG 2026-08-23). The
        # cumulative-average rate (done/elapsed) is monotonic and hides a
        # slowdown: on the 2026-08-21 run it read 91/s at 44h while the true
        # current rate was ~26/s — a ~3x ETA error. A tumbling (resettable)
        # window also misleads, because a slowdown late in the window stays
        # diluted by earlier fast work. So we keep timestamped cumulative-count
        # samples and rate = (done_now - done_oldest) / (now - oldest_ts),
        # where oldest is the sample at least `window_sec` old.
        self._window = window_sec
        self._samples: deque[tuple[float, int]] = deque()  # (monotonic, done)
        if total is not None:
            logger.info("%s — starting: %d to process", label, total)
        else:
            logger.info("%s — starting", label)

    def add(self, n: int = 1) -> None:
        self.done += n
        self._samples.append((time.monotonic(), self.done))

    def _recent_rate(self) -> float:
        now = time.monotonic()
        # Drop samples older than the window; keep the oldest one at/after
        # (now - window) as the rate baseline.
        cutoff = now - self._window
        while len(self._samples) > 1 and self._samples[1][0] < cutoff:
            self._samples.popleft()
        if not self._samples:
            return 0.0
        base_ts, base_done = self._samples[0]
        if now - base_ts < 1e-9:
            return 0.0
        return (self.done - base_done) / (now - base_ts)

    def maybe_log(self, remaining: int | None = None, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self._last) < self._every:
            return
        self._last = now
        elapsed = now - self._start
        rate = self.done / elapsed if elapsed > 0 else 0.0
        inst = self._recent_rate()

        if self.total is not None:
            # Fixed-total mode: percentage + ETA to completion (ETA uses the
            # recent rolling rate, which tracks current pace instead of the
            # lifetime average).
            rem = max(self.total - self.done, 0)
            pct = (100.0 * self.done / self.total) if self.total else 100.0
            eta = (rem / inst) if inst > 0 else None
            logger.info(
                "%-18s %7d/%-7d (%4.1f%%) | %5.0f/s (win %5.0f/s) | elapsed %s | ETA %s",
                self.label,
                self.done,
                self.total,
                pct,
                rate,
                inst,
                _fmt(elapsed),
                _fmt(eta),
            )
        elif remaining is not None:
            # Live-queue mode: done + queued + ETA to drain current queue.
            eta = (remaining / inst) if inst > 0 else None
            logger.info(
                "%-18s %7d done | %6d queued | %5.0f/s (win %5.0f/s) | elapsed %s | ETA %s",
                self.label,
                self.done,
                remaining,
                rate,
                inst,
                _fmt(elapsed),
                _fmt(eta),
            )
        else:
            logger.info(
                "%-18s %7d done | %5.0f/s (win %5.0f/s) | elapsed %s",
                self.label,
                self.done,
                rate,
                inst,
                _fmt(elapsed),
            )

    def finish(self) -> None:
        elapsed = time.monotonic() - self._start
        rate = self.done / elapsed if elapsed > 0 else 0.0
        logger.info(
            "%-18s complete: %d processed in %s (%.0f/s)",
            self.label,
            self.done,
            _fmt(elapsed),
            rate,
        )
