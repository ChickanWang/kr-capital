import threading
import time

import httpx


class RateLimiter:
    """Spaces calls evenly: at most `calls` per `period` seconds within this process.

    Other processes (API vs ETL) are not coordinated; upstream 429s are handled by retries.
    """

    def __init__(self, calls: int, period: float) -> None:
        self._interval = period / calls
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = self._next_at - now
            self._next_at = max(now, self._next_at) + self._interval
        if delay > 0:
            time.sleep(delay)


def is_retryable(exc: BaseException) -> bool:
    """Retry on rate limiting (429), server errors and network failures."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return isinstance(exc, httpx.TransportError)
