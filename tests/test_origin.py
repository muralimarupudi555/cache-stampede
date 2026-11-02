"""The origin's own bookkeeping, which decides every number downstream of it."""

from __future__ import annotations

import threading

from cache_stampede.origin import Origin


def test_a_fresh_origin_has_seen_nothing():
    assert Origin(latency_seconds=0.0).calls == 0


def test_it_counts_calls():
    origin = Origin(latency_seconds=0.0)
    for _ in range(5):
        origin.fetch("k")
    assert origin.calls == 5


def test_it_returns_a_value_for_the_key():
    assert "k" in Origin(latency_seconds=0.0).fetch("k")


def test_serial_calls_never_overlap():
    origin = Origin(latency_seconds=0.0)
    for _ in range(5):
        origin.fetch("k")
    assert origin.peak_concurrency == 1


def test_concurrent_calls_are_seen_as_concurrent():
    origin = Origin(latency_seconds=0.05)
    barrier = threading.Barrier(6)

    def one() -> None:
        barrier.wait()
        origin.fetch("k")

    threads = [threading.Thread(target=one) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert origin.peak_concurrency == 6


class TestBursts:
    def test_no_calls_is_no_bursts(self):
        assert Origin(latency_seconds=0.0).bursts(0.05) == []

    def test_calls_close_together_are_one_burst(self):
        origin = Origin(latency_seconds=0.0)
        origin.call_times = [0.0, 0.01, 0.02]
        assert origin.bursts(0.05) == [3]

    def test_a_gap_starts_a_new_burst(self):
        origin = Origin(latency_seconds=0.0)
        origin.call_times = [0.0, 0.01, 1.0, 1.01, 1.02]
        assert origin.bursts(0.05) == [2, 3]

    def test_unsorted_times_give_the_same_answer(self):
        origin = Origin(latency_seconds=0.0)
        origin.call_times = [1.01, 0.0, 1.02, 0.01, 1.0]
        assert origin.bursts(0.05) == [2, 3]

    def test_every_call_is_accounted_for(self):
        origin = Origin(latency_seconds=0.0)
        origin.call_times = [0.0, 0.01, 1.0, 2.0, 2.01]
        assert sum(origin.bursts(0.05)) == 5


class TestBusiestWindow:
    def test_an_empty_origin_has_no_busy_window(self):
        assert Origin(latency_seconds=0.0).busiest_window(0.05) == 0

    def test_it_finds_the_densest_stretch_not_the_first(self):
        origin = Origin(latency_seconds=0.0)
        origin.call_times = [0.0, 10.0, 10.01, 10.02, 20.0]
        assert origin.busiest_window(0.05) == 3

    def test_a_wider_window_hides_the_spike_in_a_rate(self):
        """Why the window has to be about as short as the stall."""
        origin = Origin(latency_seconds=0.0)
        origin.call_times = [0.0, 0.01, 0.02, 5.0, 10.0]
        assert origin.busiest_window(0.05) == 3
        assert origin.busiest_window(60.0) == 5
