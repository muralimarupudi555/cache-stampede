"""E1. The size of a stampede is the request rate times the origin's latency.

When a hot key expires the cache has nothing to serve until the refresh returns, so every
request arriving during those `d` seconds goes to the origin as well. That is `λd` of them,
plus the one that found the expiry: `1 + λd`.

Sweep both terms independently. If the derivation is right, doubling the rate and doubling
the origin's latency should each roughly double the stampede, and the measured cluster
sizes should land on the formula rather than near it - these are counts of scheduled
arrivals, not samples.

The stampede is measured as the largest cluster of origin calls, found by looking for the
gaps between them. Dividing total calls by an assumed number of expiries was the first
approach and it was wrong, because the entry's expiry is set when the fetch returns rather
than when it was asked for.
"""

from __future__ import annotations

import json
from pathlib import Path

from cache_stampede import theory
from cache_stampede.config import ScenarioConfig
from cache_stampede.harness import run_scenario

OUT = Path(__file__).resolve().parent.parent / "docs" / "experiments"
TTL = 0.5
DURATION = 3.0

RATES = (100.0, 200.0, 400.0, 800.0)
LATENCIES = (0.02, 0.05, 0.1, 0.2)
BASE_RATE = 200.0
BASE_LATENCY = 0.05


def measure(rate: float, latency: float) -> dict:
    config = ScenarioConfig(cache="naive", ttl_seconds=TTL, origin_seconds=latency,
                            request_rate=rate, duration_seconds=DURATION)
    result = run_scenario(config)
    predicted = theory.stampede_factor_exact(rate, latency)
    return {
        "request_rate": rate, "origin_seconds": latency,
        "stampede_size": result.stampede_size,
        "typical_stampede": result.typical_stampede,
        "predicted": predicted,
        "agrees": theory.agrees(result.typical_stampede, predicted),
        "origin_calls": result.origin_calls,
        "peak_concurrency": result.peak_concurrency,
        "hit_rate": round(result.hit_rate, 6),
        "pool_saturated": result.pool_saturated,
    }


def main() -> None:
    by_rate = []
    print("  sweeping the request rate at a fixed origin latency")
    for rate in RATES:
        row = measure(rate, BASE_LATENCY)
        by_rate.append(row)
        print(f"    rate {rate:6.0f}/s  stampede {row['typical_stampede']:6.1f}  "
              f"predicted {row['predicted']:4}  peak concurrent "
              f"{row['peak_concurrency']:4}  hit {row['hit_rate']:.3%}")

    by_latency = []
    print("  sweeping the origin latency at a fixed request rate")
    for latency in LATENCIES:
        row = measure(BASE_RATE, latency)
        by_latency.append(row)
        print(f"    origin {latency * 1000:5.0f}ms  stampede "
              f"{row['typical_stampede']:6.1f}  predicted {row['predicted']:4}  "
              f"peak concurrent {row['peak_concurrency']:4}  "
              f"hit {row['hit_rate']:.3%}")

    rows = by_rate + by_latency
    payload = {
        "experiment": "e1_the_stampede_factor",
        "ttl_seconds": TTL, "duration_seconds": DURATION,
        "by_rate": by_rate, "by_latency": by_latency,
        "all_agree": all(r["agrees"] for r in rows),
        "pool_never_saturated": not any(r["pool_saturated"] for r in rows),
        "worst_stampede": max(r["stampede_size"] for r in rows),
        "worst_hit_rate": min(r["hit_rate"] for r in rows),
        "best_hit_rate": max(r["hit_rate"] for r in rows),
        "rate_doubling_ratio": round(
            by_rate[-1]["typical_stampede"] / by_rate[0]["typical_stampede"], 2),
        "latency_doubling_ratio": round(
            by_latency[-1]["typical_stampede"] / by_latency[0]["typical_stampede"], 2),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e1.json").write_text(json.dumps(payload, indent=2) + "\n")

    print()
    print(f"every measured stampede lands on 1 + rate x latency: {payload['all_agree']}")
    print(f"the harness never ran out of workers:                "
          f"{payload['pool_never_saturated']}")
    print(f"eight times the rate gives {payload['rate_doubling_ratio']}x the stampede; "
          f"ten times the latency gives {payload['latency_doubling_ratio']}x")
    print(f"the worst stampede was {payload['worst_stampede']} simultaneous calls, "
          f"while no hit rate fell below {payload['worst_hit_rate']:.1%}")


if __name__ == "__main__":
    main()
