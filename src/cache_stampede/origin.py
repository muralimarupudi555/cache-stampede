"""The thing behind the cache, which takes time and keeps count.

It records two numbers that are easy to confuse and behave completely differently. The
total call count is what a request-rate graph shows. The high-water mark of simultaneous
calls is what actually knocks the origin over, and averaging it away over any window
longer than the stall makes it disappear.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Origin:
    """A slow dependency that counts how hard it is being hit."""

    latency_seconds: float
    calls: int = 0
    peak_concurrency: int = 0
    _in_flight: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    call_times: list[float] = field(default_factory=list)

    def fetch(self, key: str) -> str:
        with self._lock:
            self.calls += 1
            self._in_flight += 1
            self.peak_concurrency = max(self.peak_concurrency, self._in_flight)
            self.call_times.append(time.perf_counter())
        try:
            time.sleep(self.latency_seconds)
            return f"value-for-{key}"
        finally:
            with self._lock:
                self._in_flight -= 1

    def busiest_window(self, window_seconds: float) -> int:
        """Most calls started inside any window of this length.

        This is the number an alert would have to be looking at to notice a stampede, and
        the window has to be about as short as the stall. Widen it and the spike is
        averaged into a rate that looks fine.
        """
        with self._lock:
            ordered = sorted(self.call_times)
        best = 0
        start = 0
        for end, current in enumerate(ordered):
            while ordered[start] <= current - window_seconds:
                start += 1
            best = max(best, end - start + 1)
        return best

    def bursts(self, gap_seconds: float) -> list[int]:
        """Group the calls into refreshes, by looking for the gaps between them.

        A stampede is a cluster of calls starting within one origin latency of each
        other, separated from the next cluster by a whole time to live. Counting clusters
        instead of dividing by an assumed cycle length matters: the entry's expiry is set
        when the fetch *returns*, so the real cycle is the time to live plus the origin
        latency, and an earlier version of this measurement divided by the time to live
        alone and under-reported every stampede by about a fifth.
        """
        with self._lock:
            ordered = sorted(self.call_times)
        if not ordered:
            return []
        groups = [1]
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if current - previous > gap_seconds:
                groups.append(1)
            else:
                groups[-1] += 1
        return groups

    def as_dict(self) -> dict:
        return {
            "calls": self.calls, "peak_concurrency": self.peak_concurrency,
            "latency_seconds": self.latency_seconds,
        }
