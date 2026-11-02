"""E3. Three fixes, what each one actually removes, and what it charges for it.

Jitter, single flight and early recomputation are the standard answers. They are not
interchangeable, they do not fix the same thing, and one of them does nothing at all for
the case people usually reach for it.

**One hot key.** Jitter cannot help here and the measurement should say so plainly: a
single key has one expiry however that expiry was chosen, so spreading it moves the
stampede without shrinking it. Single flight collapses the stampede to one call. Early
recomputation does too, and additionally removes the stall, because it refreshes while the
old value is still serveable instead of after it has gone.

**Many keys populated together.** This is the case jitter is actually for. Keys filled in
the same instant expire in the same instant, so the origin takes every key's stampede at
once. Spreading the expiries spreads that load, and the measurement should show it working.

Creating that condition takes a deliberate prefill, which is worth saying because the first
version of this experiment did not do it. Left alone, keys drift apart by themselves - each
is refreshed whenever its own requests happen to arrive - so jitter was being measured
against keys that were already spread out, and it barely helped. That was a true
measurement of the wrong scenario. The prefill reproduces what a deploy or a cache flush
does, which is the situation the advice is actually about.

The cost of each is measured rather than waved at. Single flight makes readers wait on one
another. Early recomputation hands back values it knows are about to be replaced, and the
number of those is counted.

Comparisons are made on the median cluster rather than the largest. On a two-core box
running eleven concurrent sleeps, one pair of refresh cycles occasionally merges into a
single cluster, and a maximum over ten clusters is dominated by whether that happened. The
median is eleven on every seed tried.
"""

from __future__ import annotations

import json
from pathlib import Path

from cache_stampede import theory
from cache_stampede.config import ScenarioConfig
from cache_stampede.harness import run_scenario

OUT = Path(__file__).resolve().parent.parent / "docs" / "experiments"
TTL = 0.5
ORIGIN = 0.05
RATE = 200.0
DURATION = 6.0
MANY_KEYS = 20
MANY_RATE = 600.0

CACHES = ("naive", "jittered", "single_flight", "early_recompute")


def run(cache: str, keys: int, rate: float, prefill: bool = False) -> dict:
    config = ScenarioConfig(cache=cache, ttl_seconds=TTL, origin_seconds=ORIGIN,
                            request_rate=rate, duration_seconds=DURATION, keys=keys,
                            prefill=prefill)
    result = run_scenario(config)
    payload = result.as_dict()
    return {
        "cache": cache, "keys": keys,
        "stampede_size": result.stampede_size,
        "typical_stampede": result.typical_stampede,
        "peak_concurrency": result.peak_concurrency,
        "origin_calls": result.origin_calls,
        "hit_rate": round(result.hit_rate, 6),
        "stalled_requests": result.stalled_requests,
        "stalled_share": round(result.stalled_share, 5),
        "latency_p99_ms": round(result.latency_p99_ms, 3),
        "stale_serves": payload.get("stale_serves", 0),
        "waited_on_another_reader": payload.get("waited_on_another_reader", 0),
        "pool_saturated": result.pool_saturated,
    }


def main() -> None:
    predicted = theory.stampede_factor_exact(RATE, ORIGIN)
    print(f"  one hot key, predicted naive stampede {predicted}")
    hot = []
    for cache in CACHES:
        row = run(cache, 1, RATE)
        hot.append(row)
        print(f"    {cache:16} stampede {row['typical_stampede']:5.1f} "
              f"(worst {row['stampede_size']:3})  "
              f"origin calls {row['origin_calls']:4}  "
              f"stalled {row['stalled_share']:7.2%}  "
              f"hit {row['hit_rate']:.3%}  stale {row['stale_serves']:4}")

    print(f"  {MANY_KEYS} keys filled together, then left to expire together")
    many = []
    for cache in ("naive", "jittered"):
        row = run(cache, MANY_KEYS, MANY_RATE, prefill=True)
        many.append(row)
        print(f"    {cache:16} peak concurrent origin calls "
              f"{row['peak_concurrency']:4}  origin calls {row['origin_calls']:5}")

    naive_hot = hot[0]
    jittered_hot = hot[1]
    single_hot = hot[2]
    early_hot = hot[3]
    naive_many, jittered_many = many

    payload = {
        "experiment": "e3_what_the_fixes_do",
        "ttl_seconds": TTL, "origin_seconds": ORIGIN, "request_rate": RATE,
        "duration_seconds": DURATION, "many_keys": MANY_KEYS,
        "many_keys_rate": MANY_RATE,
        "hot_key": hot, "many_keys_rows": many,
        "predicted_naive_stampede": predicted,
        # Claims are made about the median cluster, not the largest. A maximum over ten
        # clusters is dominated by whichever one happened to merge with its neighbour
        # when the machine was busy; the median of the same ten is 11 on every seed
        # tried. The largest is still reported, as an observation rather than a basis.
        "jitter_does_nothing_for_one_key": (
            jittered_hot["typical_stampede"] >= naive_hot["typical_stampede"] * 0.9),
        "single_flight_collapses_it": single_hot["typical_stampede"] == 1,
        "early_recompute_collapses_it": early_hot["typical_stampede"] == 1,
        "early_recompute_stalls_fewer": (
            early_hot["stalled_requests"] < single_hot["stalled_requests"]),
        "jitter_helps_many_keys": (
            jittered_many["peak_concurrency"] < naive_many["peak_concurrency"]),
        "naive_hot_stampede": naive_hot["typical_stampede"],
        "jittered_hot_stampede": jittered_hot["typical_stampede"],
        "naive_hot_worst": naive_hot["stampede_size"],
        "single_flight_stalled_share": single_hot["stalled_share"],
        "early_stalled_share": early_hot["stalled_share"],
        "early_stale_serves": early_hot["stale_serves"],
        "naive_many_peak": naive_many["peak_concurrency"],
        "jittered_many_peak": jittered_many["peak_concurrency"],
        "jitter_peak_reduction": round(
            naive_many["peak_concurrency"] / jittered_many["peak_concurrency"], 2),
        "stall_reduction": round(
            single_hot["stalled_requests"] / max(1, early_hot["stalled_requests"]), 2),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e3.json").write_text(json.dumps(payload, indent=2) + "\n")

    print()
    print(f"jitter did nothing for one hot key:        "
          f"{payload['jitter_does_nothing_for_one_key']} "
          f"({naive_hot['typical_stampede']:.0f} against "
          f"{jittered_hot['typical_stampede']:.0f})")
    print(f"single flight collapsed it to one call:    "
          f"{payload['single_flight_collapses_it']}")
    print(f"early recomputation did too, and stalled "
          f"{payload['stall_reduction']}x fewer requests doing it")
    print(f"jitter did help {MANY_KEYS} keys filled together: "
          f"{payload['jitter_helps_many_keys']} "
          f"({naive_many['peak_concurrency']} down to "
          f"{jittered_many['peak_concurrency']} simultaneous calls)")


if __name__ == "__main__":
    main()
