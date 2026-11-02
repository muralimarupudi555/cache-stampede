"""Scenario configuration, validated on construction."""

from __future__ import annotations

from dataclasses import dataclass

CACHES = ("naive", "single_flight", "jittered", "early_recompute")

MIN_EXPIRIES = 4


class ConfigError(ValueError):
    """Raised when a run would measure something other than a stampede."""


@dataclass(frozen=True)
class ScenarioConfig:
    """One run: a cache, an origin that takes time, and a rate of arrivals."""

    cache: str = "naive"
    ttl_seconds: float = 0.5
    origin_seconds: float = 0.05
    request_rate: float = 200.0
    duration_seconds: float = 3.0
    jitter_share: float = 0.2
    early_beta: float = 1.0
    keys: int = 1
    prefill: bool = False
    seed: int = 20260219

    def __post_init__(self) -> None:
        if self.cache not in CACHES:
            raise ConfigError(f"cache must be one of {CACHES}, got {self.cache!r}")
        if self.ttl_seconds <= 0:
            raise ConfigError("ttl_seconds must be positive")
        if self.origin_seconds <= 0:
            raise ConfigError(
                "origin_seconds must be positive. An origin that answers instantly has "
                "no window for anyone else to miss in, which is the absence of the "
                "effect rather than a measurement of it."
            )
        if self.origin_seconds >= self.ttl_seconds:
            raise ConfigError(
                f"origin_seconds={self.origin_seconds} is not below "
                f"ttl_seconds={self.ttl_seconds}. A refresh that outlasts the entry it "
                "is refreshing never finishes catching up, and the run would measure a "
                "permanently cold cache."
            )
        if self.request_rate <= 0:
            raise ConfigError("request_rate must be positive")
        if self.duration_seconds / self.ttl_seconds < MIN_EXPIRIES:
            raise ConfigError(
                f"duration_seconds={self.duration_seconds} covers fewer than "
                f"{MIN_EXPIRIES} expiries at ttl_seconds={self.ttl_seconds}. The effect "
                "is counted per expiry, and a handful of them is not a measurement."
            )
        if not 0.0 <= self.jitter_share < 1.0:
            raise ConfigError("jitter_share must be in [0, 1)")
        if self.cache == "jittered" and self.jitter_share == 0:
            raise ConfigError(
                "a jittered cache with no jitter is the naive cache under another name, "
                "and would report the naive result as though a fix had been tested"
            )
        if self.early_beta <= 0:
            raise ConfigError("early_beta must be positive")
        if self.keys < 1:
            raise ConfigError("keys must be at least one")
        if self.prefill and self.keys < 2:
            raise ConfigError(
                "prefill exists to make many keys expire together, so it needs more "
                "than one key; with a single key it changes nothing"
            )

    @property
    def expected_requests(self) -> int:
        return int(self.request_rate * self.duration_seconds)

    def as_dict(self) -> dict:
        return {
            "cache": self.cache, "ttl_seconds": self.ttl_seconds,
            "origin_seconds": self.origin_seconds, "request_rate": self.request_rate,
            "duration_seconds": self.duration_seconds,
            "jitter_share": self.jitter_share, "early_beta": self.early_beta,
            "keys": self.keys, "prefill": self.prefill, "seed": self.seed,
        }
