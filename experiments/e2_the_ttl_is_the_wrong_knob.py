"""E2. Turning the TTL up improves every number except the one that matters.

The derivation in E1 has no `T` in it. The stampede is `1 + λd`, so changing the time to
live cannot change how many calls arrive at once - it can only change how often that
happens. Sweep it and watch three things move in three different ways:

- the stampede size should not move at all,
- the number of stampedes should fall in proportion to `1 / (T + d)`,
- the hit rate should climb towards one.

That third one is the trap. An operator who lengthens the TTL sees the hit rate improve
and the total origin traffic fall, concludes the cache is now working, and has not touched
the height of the spike that was knocking the origin over. The incident simply becomes
rarer, which also makes it harder to catch and easier to blame on something else.
"""

from __future__ import annotations

import json
from pathlib import Path

from cache_stampede import theory
from cache_stampede.config import ScenarioConfig
from cache_stampede.harness import run_scenario

OUT = Path(__file__).resolve().parent.parent / "docs" / "experiments"
TTLS = (0.25, 0.5, 1.0, 2.0)
RATE = 200.0
ORIGIN = 0.05
DURATION = 10.0


def main() -> None:
    predicted_size = theory.stampede_factor_exact(RATE, ORIGIN)
    rows = []
    for ttl in TTLS:
        config = ScenarioConfig(cache="naive", ttl_seconds=ttl, origin_seconds=ORIGIN,
                                request_rate=RATE, duration_seconds=DURATION)
        result = run_scenario(config)
        rows.append({
            "ttl_seconds": ttl,
            "stampede_size": result.stampede_size,
            "typical_stampede": result.typical_stampede,
            "predicted_stampede": predicted_size,
            "stampedes": len(result.bursts),
            "predicted_stampedes": round(
                theory.expiries_in(DURATION, ttl, ORIGIN), 2),
            "origin_calls": result.origin_calls,
            "hit_rate": round(result.hit_rate, 6),
            "predicted_hit_rate": round(
                1 - theory.predicted_miss_rate(ttl, RATE, ORIGIN, False), 6),
            "pool_saturated": result.pool_saturated,
        })
        print(f"  ttl {ttl:5.2f}s  stampede {result.typical_stampede:6.1f} "
              f"(predicted {predicted_size:3})  stampedes {len(result.bursts):3}  "
              f"origin calls {result.origin_calls:5}  hit {result.hit_rate:.3%}")

    sizes = {r["typical_stampede"] for r in rows}
    size_unchanged = len(sizes) == 1
    counts = [r["stampedes"] for r in rows]
    counts_fall = counts == sorted(counts, reverse=True)
    hit_rates = [r["hit_rate"] for r in rows]
    hit_rate_climbs = hit_rates == sorted(hit_rates)
    calls = [r["origin_calls"] for r in rows]

    payload = {
        "experiment": "e2_the_ttl_is_the_wrong_knob",
        "request_rate": RATE, "origin_seconds": ORIGIN,
        "duration_seconds": DURATION, "rows": rows,
        "predicted_stampede": predicted_size,
        "stampede_size_unchanged_by_ttl": size_unchanged,
        "stampede_count_falls_with_ttl": counts_fall,
        "hit_rate_climbs_with_ttl": hit_rate_climbs,
        "total_calls_fall_with_ttl": calls == sorted(calls, reverse=True),
        "shortest_ttl": TTLS[0], "longest_ttl": TTLS[-1],
        "shortest_ttl_hit_rate": rows[0]["hit_rate"],
        "longest_ttl_hit_rate": rows[-1]["hit_rate"],
        "shortest_ttl_calls": rows[0]["origin_calls"],
        "longest_ttl_calls": rows[-1]["origin_calls"],
        "calls_reduction": round(rows[0]["origin_calls"] / rows[-1]["origin_calls"], 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "e2.json").write_text(json.dumps(payload, indent=2) + "\n")

    print()
    print(f"the stampede size never changed:        {size_unchanged} "
          f"(every run: {sorted(sizes)[0]:.0f})")
    print(f"the number of stampedes fell:           {counts_fall}")
    print(f"the hit rate climbed:                   {hit_rate_climbs} "
          f"({rows[0]['hit_rate']:.1%} to {rows[-1]['hit_rate']:.1%})")
    print(f"an eightfold TTL cut total origin calls "
          f"{payload['calls_reduction']}x and the spike not at all")


if __name__ == "__main__":
    main()
