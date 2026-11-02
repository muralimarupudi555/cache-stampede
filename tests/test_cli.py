"""Exit codes, because they are the interface a pipeline uses."""

from __future__ import annotations

import json

from cache_stampede.cli import (
    EXIT_BAD_CONFIG,
    EXIT_COALESCED,
    EXIT_STAMPEDE,
    main,
)

FAST = ["--duration-seconds", "2.5"]


def test_a_naive_cache_exits_four(capsys):
    assert main(["--cache", "naive", *FAST]) == EXIT_STAMPEDE
    assert "reached the origin at once" in capsys.readouterr().out


def test_single_flight_exits_zero():
    assert main(["--cache", "single_flight", *FAST]) == EXIT_COALESCED


def test_early_recompute_exits_zero():
    assert main(["--cache", "early_recompute", *FAST]) == EXIT_COALESCED


def test_jitter_still_exits_four():
    """It spreads expiries between keys and cannot help a single one."""
    assert main(["--cache", "jittered", *FAST]) == EXIT_STAMPEDE


def test_the_report_names_the_hit_rate_beside_the_stampede(capsys):
    main(["--cache", "naive", *FAST])
    out = capsys.readouterr().out
    assert "Nothing on a cache dashboard" in out


def test_an_instant_origin_exits_two(capsys):
    assert main(["--origin-seconds", "0", *FAST]) == EXIT_BAD_CONFIG
    assert "invalid scenario" in capsys.readouterr().err


def test_too_short_a_run_exits_two():
    assert main(["--ttl-seconds", "1.0", "--duration-seconds", "2.0"]) == EXIT_BAD_CONFIG


def test_json_output_parses(capsys):
    main(["--cache", "single_flight", "--json", *FAST])
    payload = json.loads(capsys.readouterr().out)
    assert payload["coalescing"] is True
    assert payload["stampeding"] is False


def test_the_report_shows_stale_serves_for_early_recompute(capsys):
    main(["--cache", "early_recompute", *FAST])
    assert "served while refreshing" in capsys.readouterr().out
