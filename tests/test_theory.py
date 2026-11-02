"""The stampede factor, tested as properties rather than restated as a formula."""

from __future__ import annotations

import pytest

from cache_stampede import theory


def test_a_fast_origin_still_stampedes_a_little():
    assert theory.stampede_factor(100, 0.001) == pytest.approx(1.1)


def test_the_factor_rises_with_the_request_rate():
    values = [theory.stampede_factor(r, 0.05) for r in (100, 200, 400, 800)]
    assert values == sorted(values)


def test_the_factor_rises_with_the_origin_latency():
    values = [theory.stampede_factor(200, d) for d in (0.01, 0.05, 0.1, 0.2)]
    assert values == sorted(values)


def test_doubling_either_term_roughly_doubles_the_excess():
    """The excess over one is the product, so each term scales it alike."""
    base = theory.stampede_factor(200, 0.05) - 1
    by_rate = theory.stampede_factor(400, 0.05) - 1
    by_latency = theory.stampede_factor(200, 0.1) - 1
    assert by_rate == pytest.approx(2 * base)
    assert by_latency == pytest.approx(2 * base)


def test_the_ttl_does_not_appear_in_the_factor():
    """The finding: the TTL cannot change the height of the spike.

    There is no ttl argument to pass, which is the point. The only way the time to live
    enters the arithmetic at all is through how often the window opens.
    """
    assert theory.stampede_factor(200, 0.05) == theory.stampede_factor(200, 0.05)
    assert theory.expiries_in(10, 1.0, 0.05) < theory.expiries_in(10, 0.5, 0.05)


def test_single_flight_is_one_whatever_the_load():
    assert theory.single_flight_factor() == 1


def test_the_refresh_cycle_includes_the_fetch():
    """The entry's expiry is set when the fetch returns, not when it was asked for."""
    assert theory.refresh_cycle_seconds(0.5, 0.05) == pytest.approx(0.55)


def test_ignoring_the_fetch_understates_the_cycle():
    with_fetch = theory.expiries_in(10, 0.5, 0.05)
    without = theory.expiries_in(10, 0.5, 0.0)
    assert without > with_fetch


def test_expiries_fall_as_the_ttl_rises():
    values = [theory.expiries_in(10, t, 0.05) for t in (0.25, 0.5, 1.0, 2.0)]
    assert values == sorted(values, reverse=True)


def test_the_hit_rate_looks_excellent_while_the_origin_suffers():
    """Both halves of the trap, in one assertion."""
    miss = theory.predicted_miss_rate(60, 1000, 0.05, coalescing=False)
    assert miss < 0.001
    assert theory.stampede_factor(1000, 0.05) == pytest.approx(51.0)


def test_coalescing_improves_the_miss_rate_too():
    naive = theory.predicted_miss_rate(60, 1000, 0.05, coalescing=False)
    single = theory.predicted_miss_rate(60, 1000, 0.05, coalescing=True)
    assert single < naive


def test_total_calls_are_frequency_times_height():
    calls = theory.predicted_origin_calls(10, 0.5, 200, 0.05, coalescing=False)
    expected = theory.expiries_in(10, 0.5, 0.05) * theory.stampede_factor(200, 0.05)
    assert calls == pytest.approx(expected)


def test_coalescing_cuts_total_calls_to_the_expiry_count():
    calls = theory.predicted_origin_calls(10, 0.5, 200, 0.05, coalescing=True)
    assert calls == pytest.approx(theory.expiries_in(10, 0.5, 0.05))


def test_the_exact_factor_is_the_rate_floored():
    assert theory.stampede_factor_exact(200, 0.05) == 11
    assert theory.stampede_factor_exact(201, 0.05) == 11


def test_agreement_allows_one_scheduling_edge():
    assert theory.agrees(11, 11)
    assert theory.agrees(10, 11)
    assert not theory.agrees(8, 11)
