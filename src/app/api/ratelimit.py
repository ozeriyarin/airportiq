"""Sliding-window rate limits: per IP per hour (fairness) and global per day (spend ceiling)."""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Limited:
    scope: str  # "ip" | "global"
    retry_after: int
    message: str


class RateLimiter:
    def __init__(self, *, per_ip_per_hour: int, global_per_day: int, now: Callable[[], float] = time.monotonic) -> None:
        self.per_ip, self.per_day, self.now = per_ip_per_hour, global_per_day, now
        self._ip: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def _prune(q: deque[float], cutoff: float) -> None:
        while q and q[0] <= cutoff:
            q.popleft()

    def check(self, ip: str) -> Limited | None:
        """Record one request for `ip`; None when allowed, else why and when to retry."""
        with self._lock:
            t = self.now()
            self._prune(self._global, t - 86_400)
            if len(self._global) >= self.per_day:
                return Limited("global", int(self._global[0] + 86_400 - t) + 1, "Daily request limit reached. Try again tomorrow.")
            q = self._ip.setdefault(ip, deque())
            self._prune(q, t - 3_600)
            if len(q) >= self.per_ip:
                return Limited("ip", int(q[0] + 3_600 - t) + 1, "Too many requests from your address. Try again later.")
            q.append(t)
            self._global.append(t)
            return None
