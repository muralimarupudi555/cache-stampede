"""Re-derive the stampede factor and check the recorded measurements against it.

The timings belong to this machine. The arithmetic does not: the number of requests that
reach an origin during a refresh is the arrival rate times the refresh duration, plus one,
and that holds anywhere. So the arithmetic is what gets re-checked on every verify.

It was run against tampered results before being trusted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cache_stampede import theory  # noqa: E402

EXPERIMENTS = ROOT / "docs" / "experiments"


def load(name: str) -> dict:
    path = EXPERIMENTS / name
    if not path.exists():
        raise SystemExit(f"missing {path.relative_to(ROOT)}, run `make bench` first")
    return json.loads(path.read_text())


def check_e1(problems: list[str]) -> None:
    data = load("e1.json")
    for row in data["by_rate"] + data["by_latency"]:
        predicted = theory.stampede_factor_exact(
            row["request_rate"], row["origin_seconds"])
        if predicted != row["predicted"]:
            problems.append(
                f"E1 rate={row['request_rate']} origin={row['origin_seconds']}: the "
                f"recorded prediction is {row['predicted']}, the derivation says "
                f"{predicted}"
            )
        if not theory.agrees(row["typical_stampede"], predicted):
            problems.append(
                f"E1 rate={row['request_rate']} origin={row['origin_seconds']}: measured "
                f"{row['typical_stampede']} calls per refresh against a derived "
                f"{predicted}"
            )
        if row["pool_saturated"]:
            problems.append(
                f"E1 rate={row['request_rate']}: the harness ran out of workers, which "
                "caps the stampede at the pool size"
            )
    if not data["all_agree"]:
        problems.append("E1: the run itself recorded a disagreement")


def check_e2(problems: list[str]) -> None:
    data = load("e2.json")
    predicted = theory.stampede_factor_exact(
        data["request_rate"], data["origin_seconds"])

    sizes = {row["typical_stampede"] for row in data["rows"]}
    if len(sizes) != 1:
        problems.append(
            f"E2: the stampede size varied across time to live settings ({sorted(sizes)}); "
            "the derivation has no TTL term in it, so it cannot"
        )
    for row in data["rows"]:
        if not theory.agrees(row["typical_stampede"], predicted):
            problems.append(
                f"E2 ttl={row['ttl_seconds']}: measured {row['typical_stampede']} "
                f"against a derived {predicted}"
            )
        expected_refreshes = theory.expiries_in(
            data["duration_seconds"], row["ttl_seconds"], data["origin_seconds"])
        if abs(row["stampedes"] - expected_refreshes) > max(2.0, expected_refreshes * 0.2):
            problems.append(
                f"E2 ttl={row['ttl_seconds']}: {row['stampedes']} refreshes against an "
                f"expected {expected_refreshes:.1f}"
            )
    counts = [row["stampedes"] for row in data["rows"]]
    if counts != sorted(counts, reverse=True):
        problems.append("E2: a longer time to live must mean fewer refreshes")
    hit_rates = [row["hit_rate"] for row in data["rows"]]
    if hit_rates != sorted(hit_rates):
        problems.append(
            "E2: a longer time to live must raise the hit rate, which is the trap this "
            "experiment exists to show"
        )


def check_e3(problems: list[str]) -> None:
    data = load("e3.json")
    by_cache = {row["cache"]: row for row in data["hot_key"]}

    for name in ("single_flight", "early_recompute"):
        if by_cache[name]["typical_stampede"] != theory.single_flight_factor():
            problems.append(
                f"E3 {name}: {by_cache[name]['typical_stampede']} calls per refresh; "
                "coalescing means one"
            )
    if by_cache["jittered"]["typical_stampede"] < \
            by_cache["naive"]["typical_stampede"] * 0.9:
        problems.append(
            "E3: jitter appears to have helped a single hot key, which has one expiry "
            "however that expiry was chosen; check the scenario rather than believing it"
        )
    if by_cache["early_recompute"]["stalled_requests"] >= \
            by_cache["single_flight"]["stalled_requests"]:
        problems.append(
            "E3: early recomputation refreshes while the old value is still serveable, "
            "so it must make fewer requests wait than single flight does"
        )
    if by_cache["early_recompute"]["stale_serves"] == 0:
        problems.append(
            "E3: early recomputation serves values it knows are about to be replaced; "
            "none recorded means the mechanism did not engage and its latency advantage "
            "came from somewhere else"
        )
    if not data["jitter_helps_many_keys"]:
        problems.append(
            f"E3: jitter did not reduce the peak for {data['many_keys']} keys filled "
            "together, which is the one case it is actually for"
        )


def main() -> int:
    problems: list[str] = []
    check_e1(problems)
    check_e2(problems)
    check_e3(problems)

    if problems:
        print("law check failed:\n", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"\n{len(problems)} problem(s). A recorded measurement no longer matches the "
            "arithmetic it was derived from. Re-run `make bench`, and if the problem "
            "survives, the mechanism changed and the prose needs to change with it.",
            file=sys.stderr,
        )
        return 1

    print("law check passed: every recorded run still matches the stampede arithmetic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
