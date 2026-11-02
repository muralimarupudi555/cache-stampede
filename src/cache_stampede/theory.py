"""What a cache actually asks of its origin, derived before anything was measured.

A key with a time to live of `T` seconds is refreshed when it expires. The refresh is not
instantaneous: the origin takes `d` seconds to answer. For the whole of those `d` seconds
the cache has nothing to serve, so every request that arrives in the window goes to the
origin too.

With arrivals at rate `λ`, that window contains `λd` of them, plus the one that found the
expiry in the first place::

    origin calls per expiry = 1 + λd

Three things follow, and the third is the one worth building a repository around.

**The spike is not caused by the TTL.** `T` does not appear on the right hand side. A
shorter TTL makes expiries more frequent, not smaller - each one still costs `1 + λd`
calls. Turning the TTL down to reduce the spike turns the frequency up and leaves the
height alone, and turning it up makes the spike rarer without making it survivable.

**The spike is caused by two things nobody thinks of as cache settings.** The request rate
and the origin's own latency. A slow origin is punished twice: once for being slow, and
again because being slow widens the window in which everyone else misses too.

**The hit rate cannot see any of it.** Over a run of `D` seconds there are `D / T`
expiries and `λD` requests, so the miss rate is `(1 + λd) / (λT)`. At a thousand requests
a second, a fifty millisecond origin and a sixty second TTL that is under a tenth of a
percent: a hit rate of better than 99.9%, while the origin takes fifty-one simultaneous
calls every minute. Every number on the cache dashboard is excellent and the thing behind
it is being knocked over on a schedule.

Single flight changes the arithmetic rather than the tuning: one request per expiry
recomputes and the rest wait on it, so the count is `1` whatever `λ` and `d` are.
"""

from __future__ import annotations

import math

# Arrivals are scheduled, not Poisson, so the predicted counts are exact up to the one
# request that may or may not land exactly on the window's edge. This band absorbs that
# and nothing else.
EDGE_TOLERANCE = 1.5


def stampede_factor(request_rate: float, origin_seconds: float) -> float:
    """Origin calls per expiry for a cache with no coalescing: `1 + λd`."""
    return 1.0 + request_rate * origin_seconds


def stampede_factor_exact(request_rate: float, origin_seconds: float) -> int:
    """The same, for arrivals on a fixed schedule rather than at an average rate."""
    return 1 + math.floor(request_rate * origin_seconds)


def single_flight_factor() -> int:
    """One recompute per expiry, whatever the rate and the latency are."""
    return 1


def refresh_cycle_seconds(ttl_seconds: float, origin_seconds: float) -> float:
    """How long one full cycle takes: serve for the TTL, then spend the fetch.

    The entry's expiry is set when the fetch returns, not when it was asked for, so the
    cycle is `T + d` rather than `T`. It is a small correction and it was worth finding:
    dividing total calls by `T` alone understates every stampede by `d / (T + d)`.
    """
    return ttl_seconds + origin_seconds


def expiries_in(duration_seconds: float, ttl_seconds: float,
                origin_seconds: float = 0.0) -> float:
    """How often the window opens over a run of this length."""
    cycle = refresh_cycle_seconds(ttl_seconds, origin_seconds)
    if cycle <= 0:
        return 0.0
    return duration_seconds / cycle


def predicted_origin_calls(duration_seconds: float, ttl_seconds: float,
                           request_rate: float, origin_seconds: float,
                           coalescing: bool) -> float:
    """Total origin calls over a run, which is the frequency times the height."""
    expiries = expiries_in(duration_seconds, ttl_seconds, origin_seconds)
    per_expiry = (single_flight_factor() if coalescing
                  else stampede_factor(request_rate, origin_seconds))
    return expiries * per_expiry


def predicted_miss_rate(ttl_seconds: float, request_rate: float,
                        origin_seconds: float, coalescing: bool) -> float:
    """Share of requests that reach the origin, which is what a dashboard reports."""
    if ttl_seconds <= 0 or request_rate <= 0:
        return 1.0
    per_expiry = (single_flight_factor() if coalescing
                  else stampede_factor(request_rate, origin_seconds))
    cycle = refresh_cycle_seconds(ttl_seconds, origin_seconds)
    return min(1.0, per_expiry / (request_rate * cycle))


def agrees(measured: float, predicted: float,
           tolerance: float = EDGE_TOLERANCE) -> bool:
    """Whether a measured count sits within one scheduling edge of the prediction."""
    return abs(measured - predicted) <= tolerance
