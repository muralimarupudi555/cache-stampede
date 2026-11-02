"""Read the experiment outputs and write the file every document is checked against."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from cache_stampede import theory  # noqa: E402

# The figure the README quotes to show how blind a hit rate is. It is derived rather than
# measured, so it is computed here from theory.py rather than typed into the prose, which
# keeps it inside the same check as everything else.
ILLUSTRATIVE_RATE = 1000.0
ILLUSTRATIVE_ORIGIN = 0.05
ILLUSTRATIVE_TTL = 60.0
EXPERIMENTS = ROOT / "docs" / "experiments"
OUT = ROOT / "docs" / "metrics.json"

CHECKED_DOCUMENTS = (
    "README.md",
    "docs/adr/ADR-001-four-caches-and-a-slow-origin.md",
    "docs/adr/ADR-002-an-open-loop-and-a-pool-that-never-filled.md",
    "docs/adr/ADR-003-three-scenarios-that-had-to-be-built-right.md",
    "docs/adr/ADR-004-what-this-cannot-measure.md",
)


def load(name: str) -> dict:
    path = EXPERIMENTS / name
    if not path.exists():
        raise SystemExit(
            f"missing {path.relative_to(ROOT)}. Run `make bench` first: the documents "
            "are checked against measurements."
        )
    return json.loads(path.read_text())


def count_tests() -> int:
    out = subprocess.run(
        ["python3", "-m", "pytest", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    ).stdout
    per_file = re.findall(r"^\S+\.py: (\d+)$", out, re.MULTILINE)
    if per_file:
        return sum(int(n) for n in per_file)
    for line in reversed(out.splitlines()):
        match = re.match(r"^(\d+) tests? collected", line.strip())
        if match:
            return int(match.group(1))
    node_ids = sum(1 for line in out.splitlines() if "::" in line)
    if node_ids == 0:
        raise SystemExit("could not count tests from pytest's output; fix count_tests().")
    return node_ids


def main() -> None:
    e1, e2, e3 = (load(f"e{i}.json") for i in (1, 2, 3))

    # The base row is the one both sweeps share, so it is looked up rather than
    # taken from an end of either list: an earlier version used by_rate[0], which is the
    # slowest rate and not the base at all, and labelled its stampede as the base one.
    base_rate_value = e1["by_latency"][0]["request_rate"]
    base_origin_value = e1["by_rate"][0]["origin_seconds"]
    base = next(r for r in e1["by_rate"] if r["request_rate"] == base_rate_value)
    busiest_rate = e1["by_rate"][-1]
    slowest_origin = e1["by_latency"][-1]
    short_ttl, long_ttl = e2["rows"][0], e2["rows"][-1]
    by_cache = {row["cache"]: row for row in e3["hot_key"]}

    metrics = {
        "base_rate": int(base_rate_value),
        "base_origin_ms": int(base_origin_value * 1000),
        "base_stampede": base["predicted"],
        "busiest_rate": int(busiest_rate["request_rate"]),
        "busiest_stampede": busiest_rate["predicted"],
        "slowest_origin_ms": int(slowest_origin["origin_seconds"] * 1000),
        "slowest_origin_stampede": slowest_origin["predicted"],
        "worst_hit_rate": e1["worst_hit_rate"],
        "best_hit_rate": e1["best_hit_rate"],

        "ttl_stampede": e2["predicted_stampede"],
        "short_ttl": short_ttl["ttl_seconds"],
        "long_ttl": long_ttl["ttl_seconds"],
        "short_ttl_hit_rate": short_ttl["hit_rate"],
        "long_ttl_hit_rate": long_ttl["hit_rate"],
        "short_ttl_calls": short_ttl["origin_calls"],
        "long_ttl_calls": long_ttl["origin_calls"],
        "calls_reduction": e2["calls_reduction"],

        "naive_hot_stampede": int(by_cache["naive"]["typical_stampede"]),
        "jittered_hot_stampede": int(by_cache["jittered"]["typical_stampede"]),
        "single_flight_stalled": by_cache["single_flight"]["stalled_share"],
        "early_stalled": by_cache["early_recompute"]["stalled_share"],
        "early_stale_serves": by_cache["early_recompute"]["stale_serves"],
        "stall_reduction": e3["stall_reduction"],
        "many_keys": e3["many_keys"],
        "naive_many_peak": e3["naive_many_peak"],
        "jittered_many_peak": e3["jittered_many_peak"],
        "jitter_peak_reduction": e3["jitter_peak_reduction"],

        "illustrative_rate": int(ILLUSTRATIVE_RATE),
        "illustrative_ttl": int(ILLUSTRATIVE_TTL),
        "illustrative_stampede": theory.stampede_factor_exact(
            ILLUSTRATIVE_RATE, ILLUSTRATIVE_ORIGIN),
        "illustrative_hit_rate": round(
            1 - theory.predicted_miss_rate(
                ILLUSTRATIVE_TTL, ILLUSTRATIVE_RATE, ILLUSTRATIVE_ORIGIN,
                coalescing=False), 6),

        "tests": count_tests(),
    }

    display = {
        "worst_hit_rate": f"{metrics['worst_hit_rate']:.1%}",
        "best_hit_rate": f"{metrics['best_hit_rate']:.1%}",
        "short_ttl": f"{metrics['short_ttl']:g}",
        "long_ttl": f"{metrics['long_ttl']:g}",
        "short_ttl_hit_rate": f"{metrics['short_ttl_hit_rate']:.1%}",
        "long_ttl_hit_rate": f"{metrics['long_ttl_hit_rate']:.1%}",
        "calls_reduction": f"{metrics['calls_reduction']:.1f}",
        "single_flight_stalled": f"{metrics['single_flight_stalled']:.2%}",
        "early_stalled": f"{metrics['early_stalled']:.2%}",
        "stall_reduction": f"{metrics['stall_reduction']:.1f}",
        "jitter_peak_reduction": f"{metrics['jitter_peak_reduction']:.2f}",
        "illustrative_hit_rate": f"{metrics['illustrative_hit_rate']:.2%}",
    }
    for key, value in metrics.items():
        display.setdefault(key, str(value))

    anchors = {
        "base_rate": ["{} requests a second"],
        "base_origin_ms": ["an origin taking {} ms"],
        "base_stampede": ["{} requests reach it at once"],
        "busiest_rate": ["at {} requests a second"],
        "busiest_stampede": ["becomes {}"],
        "slowest_origin_ms": ["an origin at {} ms"],
        "slowest_origin_stampede": ["also {}"],
        "worst_hit_rate": ["never fell below {}"],
        "best_hit_rate": ["as high as {}"],
        "ttl_stampede": ["stayed at {} calls"],
        "short_ttl": ["from {} seconds"],
        "long_ttl": ["to {} seconds"],
        "short_ttl_hit_rate": ["hit rate climbed from {}"],
        "long_ttl_hit_rate": ["to a hit rate of {}"],
        "short_ttl_calls": ["{} origin calls"],
        "long_ttl_calls": ["down to {}"],
        "calls_reduction": ["{}x fewer calls"],
        "naive_hot_stampede": ["admits {} calls per refresh"],
        "jittered_hot_stampede": ["jitter gives {}"],
        "single_flight_stalled": ["made {} of requests wait"],
        "early_stalled": ["waits to {}"],
        "early_stale_serves": ["{} values served"],
        "stall_reduction": ["{}x fewer requests"],
        "many_keys": ["{} keys filled together"],
        "naive_many_peak": ["peaks at {} simultaneous"],
        "jittered_many_peak": ["down to {} simultaneous"],
        "jitter_peak_reduction": ["{}x reduction"],
        "illustrative_rate": ["at {} requests a second"],
        "illustrative_ttl": ["a {} second TTL"],
        "illustrative_stampede": ["{} simultaneous calls"],
        "illustrative_hit_rate": ["a hit rate of {}"],
        "tests": ["{} tests"],
    }

    OUT.write_text(json.dumps({
        "metrics": metrics, "display": display, "anchors": anchors,
        "checked_documents": list(CHECKED_DOCUMENTS),
    }, indent=2) + "\n")
    print(f"collected {len(metrics)} metrics into {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
