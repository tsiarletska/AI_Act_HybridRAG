"""In-memory rate limits (guardrail step 1): per client per minute / per day, and a global daily cap.
Single-process MVP; a production deployment would use Redis or the gateway (see PRODUCTION.md)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import date


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, global_per_day: int):
        self.per_minute, self.per_day, self.global_per_day = per_minute, per_day, global_per_day
        self.recent: dict[str, deque] = defaultdict(deque)
        self.daily: dict[str, int] = defaultdict(int)
        self.global_count = 0
        self.day = date.today()
        self.lock = threading.Lock()

    def check(self, client: str) -> str | None:
        """Record one request; return a refusal message if over a limit."""
        with self.lock:
            if date.today() != self.day:
                self.day, self.daily, self.global_count = date.today(), defaultdict(int), 0
            now = time.monotonic()
            q = self.recent[client]
            while q and now - q[0] > 60:
                q.popleft()
            if self.global_count >= self.global_per_day:
                return "The demo has reached its daily usage limit. Please try again tomorrow."
            if self.daily[client] >= self.per_day:
                return "You have reached the daily question limit for this demo. Please try again tomorrow."
            if len(q) >= self.per_minute:
                return "Too many questions in a short time. Please wait a minute and try again."
            q.append(now)
            self.daily[client] += 1
            self.global_count += 1
            return None
