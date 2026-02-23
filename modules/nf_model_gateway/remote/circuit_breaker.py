from __future__ import annotations

import time


class CircuitBreaker:
    def __init__(self, *, failure_threshold: int = 3, recovery_seconds: int = 30) -> None:
        self._failure_threshold = max(1, failure_threshold)
        self._recovery_seconds = max(1, recovery_seconds)
        self._failures = 0
        self._opened_at: float | None = None

    def allow(self) -> bool:
        if self._opened_at is None:
            return True
        if time.monotonic() - self._opened_at >= self._recovery_seconds:
            self.reset()
            return True
        return False

    def record_success(self) -> None:
        self.reset()

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self._failure_threshold:
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        self._failures = 0
        self._opened_at = None
