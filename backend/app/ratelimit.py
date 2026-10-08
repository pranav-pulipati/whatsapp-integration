"""Small in-process sliding-window rate limiter.

Good enough for a single API instance. If you run several instances, also rate
limit at the edge (reverse proxy / load balancer).
"""

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 10_000:  # bound memory under abuse
                self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v})
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(limit=10, window_seconds=60)
webhook_limiter = RateLimiter(limit=1200, window_seconds=60)
