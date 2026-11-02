"""A run that cannot show a stampede should not start."""

from __future__ import annotations

import pytest

from cache_stampede.config import ConfigError, ScenarioConfig


def test_defaults_are_valid():
    assert ScenarioConfig().cache == "naive"


@pytest.mark.parametrize("cache", ["naive", "single_flight", "early_recompute"])
def test_caches_needing_no_extra_settings(cache):
    assert ScenarioConfig(cache=cache).cache == cache


def test_unknown_cache_refused():
    with pytest.raises(ConfigError, match="cache must be one of"):
        ScenarioConfig(cache="write_through_maybe")


def test_an_instant_origin_refused():
    """No window to miss in is the absence of the effect, not a measurement of it."""
    with pytest.raises(ConfigError, match="no window"):
        ScenarioConfig(origin_seconds=0.0)


def test_an_origin_slower_than_the_ttl_refused():
    with pytest.raises(ConfigError, match="never finishes catching up"):
        ScenarioConfig(ttl_seconds=0.05, origin_seconds=0.05)


def test_too_few_expiries_refused():
    with pytest.raises(ConfigError, match="not a measurement"):
        ScenarioConfig(ttl_seconds=1.0, duration_seconds=2.0)


def test_jitter_without_jitter_refused():
    with pytest.raises(ConfigError, match="under another name"):
        ScenarioConfig(cache="jittered", jitter_share=0.0)


def test_jitter_with_jitter_accepted():
    assert ScenarioConfig(cache="jittered", jitter_share=0.2).jitter_share == 0.2


def test_prefill_needs_more_than_one_key():
    with pytest.raises(ConfigError, match="more than one key"):
        ScenarioConfig(prefill=True, keys=1)


def test_prefill_with_many_keys_accepted():
    assert ScenarioConfig(prefill=True, keys=10).prefill


def test_expected_requests_is_rate_times_duration():
    assert ScenarioConfig(request_rate=200, duration_seconds=3).expected_requests == 600


def test_config_is_frozen():
    config = ScenarioConfig()
    with pytest.raises(AttributeError):
        config.ttl_seconds = 99  # type: ignore[misc]


def test_as_dict_round_trips():
    config = ScenarioConfig(cache="jittered", ttl_seconds=0.5, keys=4,
                            duration_seconds=4.0)
    assert ScenarioConfig(**config.as_dict()).as_dict() == config.as_dict()
