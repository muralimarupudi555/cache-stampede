"""Whole runs, where the measurement has to match the derivation."""

from __future__ import annotations

import pytest

from cache_stampede import theory
from cache_stampede.config import ScenarioConfig
from cache_stampede.harness import pool_size_for, run_scenario

RATE = 200.0
ORIGIN = 0.05
TTL = 0.5
DURATION = 2.5


def scenario(**overrides) -> ScenarioConfig:
    fields = dict(cache="naive", ttl_seconds=TTL, origin_seconds=ORIGIN,
                  request_rate=RATE, duration_seconds=DURATION)
    fields.update(overrides)
    return ScenarioConfig(**fields)


def test_the_pool_is_sized_above_the_expected_in_flight_count():
    config = scenario()
    assert pool_size_for(config) > config.request_rate * config.origin_seconds


def test_the_pool_never_saturates_on_a_naive_run():
    """A saturated pool is a closed loop wearing an open loop's clothes."""
    assert not run_scenario(scenario()).pool_saturated


def test_a_naive_run_stampedes_to_the_derived_size():
    result = run_scenario(scenario())
    predicted = theory.stampede_factor_exact(RATE, ORIGIN)
    assert theory.agrees(result.typical_stampede, predicted)


def test_single_flight_makes_one_call_per_refresh():
    result = run_scenario(scenario(cache="single_flight"))
    assert result.typical_stampede == 1
    assert result.peak_concurrency == 1


def test_early_recompute_also_makes_one_call_per_refresh():
    result = run_scenario(scenario(cache="early_recompute"))
    assert result.typical_stampede == 1


def test_jitter_does_not_help_a_single_hot_key():
    naive = run_scenario(scenario()).typical_stampede
    jittered = run_scenario(scenario(cache="jittered")).typical_stampede
    assert jittered >= naive * 0.9


def test_coalescing_cuts_total_origin_calls_severalfold():
    naive = run_scenario(scenario()).origin_calls
    single = run_scenario(scenario(cache="single_flight")).origin_calls
    assert naive > 3 * single


def test_the_hit_rate_stays_high_even_while_stampeding():
    """The metric that cannot see the problem, demonstrated."""
    assert run_scenario(scenario()).hit_rate > 0.8


def test_early_recompute_stalls_fewer_requests_than_single_flight():
    single = run_scenario(scenario(cache="single_flight")).stalled_requests
    early = run_scenario(scenario(cache="early_recompute")).stalled_requests
    assert early < single


def test_early_recompute_pays_for_it_in_staleness():
    result = run_scenario(scenario(cache="early_recompute"))
    assert result.as_dict()["stale_serves"] > 0


def test_bursts_account_for_every_origin_call():
    result = run_scenario(scenario())
    assert sum(result.bursts) == result.origin_calls


def test_prefill_is_not_counted_in_the_measurement(dsn=None):
    """The warm-up fills every key; none of that may land in the result."""
    result = run_scenario(scenario(keys=4, prefill=True, request_rate=400.0))
    assert result.origin_calls < 4 * result.requests
    assert sum(result.bursts) == result.origin_calls


@pytest.mark.parametrize("cache", ["naive", "jittered", "single_flight",
                                   "early_recompute"])
def test_every_cache_serves_every_request(cache):
    result = run_scenario(scenario(cache=cache))
    assert result.requests == result.hits + result.misses
