"""In-process rate limiters for the unauthenticated room paths.

`TurnRateLimiter`: one call per `interval_s` per key (the per-player turn cadence).
`WindowLimiter`: at most `max_calls` per `window_s` per key (per-address bursts, join floods).
Both are keyed by strings the caller chooses, bounded in memory, and use the monotonic clock.
"""

from __future__ import annotations

import threading
import time
from collections import deque

FORM_TURN_INTERVAL_S = 3.0  # same as RoomStore.submit_turn and the SpacetimeDB reducer
ADDRESS_BURST = 3  # turns per address per window, form path and memory /submit alike
ADDRESS_WINDOW_S = 3.0
JOIN_BURST = 5  # joins per address per minute
JOIN_WINDOW_S = 60.0
MAX_KEYS = 10_000


class TurnRateLimiter:
    """One call per `interval_s` per key. Raises nothing: `allow` returns False when too soon."""

    def __init__(self, interval_s: float = FORM_TURN_INTERVAL_S) -> None:
        self.interval_s = interval_s
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            last = self._last.get(key)
            if last is not None and now - last < self.interval_s:
                return False
            self._last[key] = now
            if len(self._last) > MAX_KEYS:
                for k in [k for k, t in self._last.items() if now - t > self.interval_s]:
                    del self._last[k]
            return True

    def reset(self) -> None:
        with self._lock:
            self._last.clear()


class WindowLimiter:
    """At most `max_calls` per `window_s` per key (sliding window). Bounded table."""

    def __init__(self, max_calls: int, window_s: float) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._hits.get(key)
            if q is None:
                q = deque()
                self._hits[key] = q
            while q and now - q[0] >= self.window_s:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            if len(self._hits) > MAX_KEYS:
                for k in [
                    k for k, d in self._hits.items() if not d or now - d[-1] >= self.window_s
                ]:
                    del self._hits[k]
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
