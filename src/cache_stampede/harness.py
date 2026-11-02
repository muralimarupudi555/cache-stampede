"""Drive requests at a fixed rate and record what reached the origin.

Open loop. Arrivals are scheduled in advance at `1/λ` intervals and dispatched when their
time comes, whether or not earlier ones have finished. That matters more here than in most
measurements: a closed loop with `C` workers cannot send more than `C` requests into a
stall, so it would report a stampede of `C` whatever the request rate was, and `C` is a
property of the harness rather than of the system. ADR-002 argues it.

The thread pool is sized well above the number of requests expected to be in flight during
a stall, and the harness checks afterwards that it never ran out of workers. A measurement
taken against a saturated pool is a closed loop wearing an open loop's clothes.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from cache_stampede import theory
from cache_stampede.caches import Cache, build
from cache_stampede.config import ScenarioConfig
from cache_stampede.origin import Origin

# How much headroom the pool gets over the worst expected in-flight count. Three times is
# generous; the point is that the pool must never be the thing that limits the stampede.
POOL_HEADROOM = 3


@dataclass(frozen=True)
class RunResult:
    """One run: what the cache reported, and what the origin actually took."""

    config: ScenarioConfig
    requests: int
    hits: int
    misses: int
    origin_calls: int
    peak_concurrency: int
    busiest_window: int
    bursts: list[int]
    expiries: float
    wall_seconds: float
    latency_p50_ms: float
    latency_p99_ms: float
    stalled_requests: int
    pool_size: int
    peak_in_flight: int
    extras: dict

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0

    @property
    def calls_per_expiry(self) -> float:
        return self.origin_calls / self.expiries if self.expiries else 0.0

    @property
    def stampede_size(self) -> int:
        """The biggest cluster of origin calls, which is what the origin has to survive.

        Taken from the clusters rather than from an average, because an average over
        anything longer than the stall is exactly the number that hides this.
        """
        return max(self.bursts, default=0)

    @property
    def typical_stampede(self) -> float:
        if not self.bursts:
            return 0.0
        ordered = sorted(self.bursts)
        return float(ordered[len(ordered) // 2])

    @property
    def stalled_share(self) -> float:
        """Share of requests that waited on the origin rather than being served.

        This is the number a user feels, and it separates the fixes in a way that a
        percentile cannot. A p99 catches whichever requests did the refreshing whatever
        the cache does, because there is always at least one; what changes between these
        caches is how many requests are made to wait for it.
        """
        return self.stalled_requests / self.requests if self.requests else 0.0

    @property
    def pool_saturated(self) -> bool:
        """Whether the harness ever ran out of workers, which would bias everything."""
        return self.peak_in_flight >= self.pool_size

    def as_dict(self) -> dict:
        return {
            "config": self.config.as_dict(), "requests": self.requests,
            "hits": self.hits, "misses": self.misses,
            "hit_rate": round(self.hit_rate, 6),
            "origin_calls": self.origin_calls,
            "calls_per_expiry": round(self.calls_per_expiry, 3),
            "bursts": self.bursts,
            "stampede_size": self.stampede_size,
            "typical_stampede": self.typical_stampede,
            "peak_concurrency": self.peak_concurrency,
            "busiest_window": self.busiest_window,
            "expiries": round(self.expiries, 3),
            "wall_seconds": round(self.wall_seconds, 4),
            "latency_p50_ms": round(self.latency_p50_ms, 3),
            "latency_p99_ms": round(self.latency_p99_ms, 3),
            "stalled_requests": self.stalled_requests,
            "stalled_share": round(self.stalled_share, 5),
            "pool_size": self.pool_size, "peak_in_flight": self.peak_in_flight,
            "pool_saturated": self.pool_saturated,
            **self.extras,
        }


def _percentile(ordered: list[float], q: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


def pool_size_for(config: ScenarioConfig) -> int:
    """Enough workers that the pool is never the binding constraint."""
    in_flight = config.request_rate * config.origin_seconds
    return max(16, int(math.ceil(in_flight * POOL_HEADROOM)) + 8)


def run_scenario(config: ScenarioConfig) -> RunResult:
    """Send requests at the configured rate and measure what the origin saw."""
    origin = Origin(latency_seconds=config.origin_seconds)
    cache: Cache = build(config.cache, origin, config.ttl_seconds, config.seed,
                         config.jitter_share, config.early_beta)

    keys = [f"key-{i}" for i in range(config.keys)]
    total = config.expected_requests
    interval = 1.0 / config.request_rate
    latencies: list[float] = []
    in_flight = 0
    peak_in_flight = 0
    pool = pool_size_for(config)

    def one(index: int) -> None:
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        started = time.perf_counter()
        try:
            cache.get(keys[index % len(keys)])
        finally:
            latencies.append((time.perf_counter() - started) * 1000.0)
            in_flight -= 1

    if config.prefill:
        # Fill every key at once, which is what a deploy, a flush or a cold start does.
        # Without this the keys drift apart on their own - each is refreshed when its own
        # requests happen to arrive - and the synchronised expiry that jitter exists to
        # break up never forms. An earlier version of E3 measured jitter against keys
        # that were already spread out and found it barely helped, which was a true
        # statement about the wrong scenario.
        with ThreadPoolExecutor(max_workers=len(keys)) as warmer:
            list(warmer.map(cache.get, keys))
        cache.hits = 0
        cache.misses = 0
        origin.calls = 0
        origin.peak_concurrency = 0
        origin.call_times.clear()

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=pool) as executor:
        for index in range(total):
            due = started + index * interval
            delay = due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            executor.submit(one, index)
    wall = time.perf_counter() - started

    ordered = sorted(latencies)
    extras = {}
    payload = cache.as_dict()
    for key in ("early_refreshes", "stale_serves"):
        if key in payload:
            extras[key] = payload[key]
    if hasattr(cache, "waited"):
        extras["waited_on_another_reader"] = cache.waited

    return RunResult(
        config=config, requests=len(latencies), hits=cache.hits, misses=cache.misses,
        origin_calls=origin.calls, peak_concurrency=origin.peak_concurrency,
        busiest_window=origin.busiest_window(config.origin_seconds),
        bursts=origin.bursts(config.origin_seconds),
        expiries=max(1.0, wall / theory.refresh_cycle_seconds(
            config.ttl_seconds, config.origin_seconds)),
        wall_seconds=wall,
        latency_p50_ms=_percentile(ordered, 0.50),
        latency_p99_ms=_percentile(ordered, 0.99),
        stalled_requests=sum(
            1 for value in ordered if value >= config.origin_seconds * 1000 * 0.5),
        pool_size=pool, peak_in_flight=peak_in_flight, extras=extras,
    )
