from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, *, max_calls: int = 60, period_seconds: int = 60) -> None:
        self._max_calls = max(1, max_calls)
        self._period = max(1, period_seconds)
        self._calls: deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        cutoff = now - self._period
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()
        if len(self._calls) >= self._max_calls:
            return False
        self._calls.append(now)
        return True
