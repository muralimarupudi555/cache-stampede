"""Turn a run into a verdict, and check the apparatus while doing it.

Two things have to be true before a stampede figure is worth printing. The harness must
not have run out of workers, because a saturated pool caps the stampede at the pool size
and would report a property of the harness as a property of the cache. And for a cache
with no coalescing, the measured cluster must land on `1 + λd`, because that count is
arithmetic over scheduled arrivals rather than a sample, and a run that misses it is
measuring something else.
"""

from __future__ import annotations

from dataclasses import dataclass

from cache_stampede import theory
from cache_stampede.config import ScenarioConfig
from cache_stampede.harness import RunResult, run_scenario

COALESCING = ("single_flight", "early_recompute")


@dataclass(frozen=True)
class Report:
    result: RunResult

    @property
    def config(self) -> ScenarioConfig:
        return self.result.config

    @property
    def coalescing(self) -> bool:
        return self.config.cache in COALESCING

    @property
    def predicted_stampede(self) -> int:
        if self.coalescing:
            return theory.single_flight_factor()
        return theory.stampede_factor_exact(
            self.config.request_rate, self.config.origin_seconds)

    @property
    def predicted_hit_rate(self) -> float:
        return 1.0 - theory.predicted_miss_rate(
            self.config.ttl_seconds, self.config.request_rate,
            self.config.origin_seconds, self.coalescing)

    @property
    def stampede_agrees(self) -> bool:
        return theory.agrees(self.result.typical_stampede, self.predicted_stampede)

    @property
    def measurement_valid(self) -> bool:
        if self.result.pool_saturated:
            return False
        if self.config.keys > 1:
            # With several keys the per-key rate is a share of the total and the clusters
            # interleave, so the single-key derivation does not apply and is not checked.
            return True
        return self.stampede_agrees

    @property
    def stampeding(self) -> bool:
        return self.result.typical_stampede > 1

    @property
    def amplification(self) -> float:
        return self.result.typical_stampede

    def as_dict(self) -> dict:
        return {
            **self.result.as_dict(),
            "predicted_stampede": self.predicted_stampede,
            "predicted_hit_rate": round(self.predicted_hit_rate, 6),
            "stampede_agrees": self.stampede_agrees,
            "measurement_valid": self.measurement_valid,
            "stampeding": self.stampeding,
            "coalescing": self.coalescing,
        }


def build_report(config: ScenarioConfig) -> Report:
    return Report(result=run_scenario(config))
