"""The four caches, driven by hand with a fake origin so the behaviour is exact."""

from __future__ import annotations

import threading
import time

import pytest

from cache_stampede.caches import (
    EarlyRecompute,
    JitteredTTL,
    NaiveTTL,
    SingleFlight,
    build,
)
from cache_stampede.origin import Origin

FAST = 0.01
TTL = 0.2


def origin(latency: float = FAST) -> Origin:
    return Origin(latency_seconds=latency)


def hammer(cache, key: str, readers: int) -> None:
    """Send `readers` requests at a key at the same instant."""
    barrier = threading.Barrier(readers)

    def one() -> None:
        barrier.wait()
        cache.get(key)

    threads = [threading.Thread(target=one) for _ in range(readers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()


def test_build_returns_each_cache():
    source = origin()
    for name in ("naive", "jittered", "single_flight", "early_recompute"):
        assert build(name, source, TTL).name == name


def test_build_refuses_an_unknown_name():
    with pytest.raises(ValueError, match="unknown cache"):
        build("hopeful", origin(), TTL)


class TestNaiveTTL:
    def test_a_cold_key_goes_to_the_origin(self):
        source = origin()
        NaiveTTL(source, TTL).get("k")
        assert source.calls == 1

    def test_a_warm_key_does_not(self):
        source = origin()
        cache = NaiveTTL(source, TTL)
        cache.get("k")
        cache.get("k")
        assert source.calls == 1
        assert cache.hits == 1

    def test_an_expired_key_goes_again(self):
        source = origin()
        cache = NaiveTTL(source, 0.02)
        cache.get("k")
        time.sleep(0.05)
        cache.get("k")
        assert source.calls == 2

    def test_every_concurrent_reader_of_a_cold_key_fetches(self):
        """The stampede, in one assertion."""
        source = origin(latency=0.05)
        hammer(NaiveTTL(source, TTL), "k", 8)
        assert source.calls == 8
        assert source.peak_concurrency > 1


class TestJitteredTTL:
    def test_it_still_stampedes_on_one_key(self):
        """Jitter spreads expiries between keys and cannot help a single one."""
        source = origin(latency=0.05)
        hammer(JitteredTTL(source, TTL, jitter_share=0.5), "k", 8)
        assert source.calls == 8

    def test_the_ttl_varies_between_keys(self):
        cache = JitteredTTL(origin(), TTL, seed=3, jitter_share=0.5)
        draws = {round(cache._ttl_for(f"k{i}"), 6) for i in range(20)}
        assert len(draws) > 1

    def test_the_jittered_ttl_stays_near_the_nominal_one(self):
        cache = JitteredTTL(origin(), TTL, seed=3, jitter_share=0.2)
        for _ in range(50):
            assert TTL * 0.8 <= cache._ttl_for("k") <= TTL * 1.2


class TestSingleFlight:
    def test_only_one_concurrent_reader_fetches(self):
        source = origin(latency=0.05)
        cache = SingleFlight(source, TTL)
        hammer(cache, "k", 8)
        assert source.calls == 1
        assert source.peak_concurrency == 1

    def test_the_others_are_counted_as_having_waited(self):
        source = origin(latency=0.05)
        cache = SingleFlight(source, TTL)
        hammer(cache, "k", 8)
        assert cache.waited == 7

    def test_different_keys_do_not_block_each_other(self):
        source = origin(latency=0.05)
        cache = SingleFlight(source, TTL)
        threads = [threading.Thread(target=cache.get, args=(f"k{i}",)) for i in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert source.calls == 4
        assert source.peak_concurrency > 1

    def test_a_warm_key_takes_no_lock(self):
        source = origin()
        cache = SingleFlight(source, TTL)
        cache.get("k")
        hammer(cache, "k", 8)
        assert source.calls == 1


class TestEarlyRecompute:
    def test_a_cold_key_still_coalesces(self):
        source = origin(latency=0.05)
        cache = EarlyRecompute(source, TTL)
        hammer(cache, "k", 8)
        assert source.calls == 1

    def test_readers_are_served_the_old_value_during_a_refresh(self):
        """The distinguishing property: nobody waits, because nothing is ever missing."""
        source = origin(latency=0.05)
        cache = EarlyRecompute(source, 0.06, beta=50.0)
        cache.get("k")
        hammer(cache, "k", 8)
        assert cache.stale_serves > 0

    def test_it_refreshes_before_the_entry_expires(self):
        source = origin(latency=0.02)
        cache = EarlyRecompute(source, 0.3, beta=100.0)
        cache.get("k")
        for _ in range(20):
            cache.get("k")
            time.sleep(0.005)
        assert cache.early_refreshes > 0

    def test_a_small_beta_refreshes_less_eagerly(self):
        eager = EarlyRecompute(origin(), 0.3, seed=1, beta=100.0)
        patient = EarlyRecompute(origin(), 0.3, seed=1, beta=0.001)
        for cache in (eager, patient):
            cache.get("k")
            for _ in range(20):
                cache.get("k")
                time.sleep(0.002)
        assert eager.early_refreshes >= patient.early_refreshes
