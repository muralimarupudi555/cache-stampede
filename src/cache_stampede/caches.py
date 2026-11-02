"""Four caches: one that stampedes and three attempts to stop it.

All four share the same interface and the same origin, so the only thing that differs
between runs is what happens at the moment an entry expires.
"""

from __future__ import annotations

import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

from cache_stampede.origin import Origin


@dataclass
class Entry:
    value: str
    expires_at: float
    computed_in: float = 0.0


class Cache(ABC):
    name: str

    def __init__(self, origin: Origin, ttl_seconds: float, seed: int = 0) -> None:
        self.origin = origin
        self.ttl_seconds = ttl_seconds
        self.rng = random.Random(seed)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._entries: dict[str, Entry] = {}

    @abstractmethod
    def get(self, key: str) -> str:
        """Return the value, going to the origin if this reader has to."""

    def _ttl_for(self, key: str) -> float:
        return self.ttl_seconds

    def _store(self, key: str, value: str, computed_in: float) -> Entry:
        entry = Entry(value=value,
                      expires_at=time.perf_counter() + self._ttl_for(key),
                      computed_in=computed_in)
        with self._lock:
            self._entries[key] = entry
        return entry

    def _fresh(self, key: str) -> Entry | None:
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or entry.expires_at <= time.perf_counter():
            return None
        return entry

    def as_dict(self) -> dict:
        total = self.hits + self.misses
        return {
            "cache": self.name, "hits": self.hits, "misses": self.misses,
            "hit_rate": round(self.hits / total, 6) if total else 0.0,
        }


class NaiveTTL(Cache):
    """Check, and on a miss go and fetch. The version almost everyone writes."""

    name = "naive"

    def get(self, key: str) -> str:
        entry = self._fresh(key)
        if entry is not None:
            self.hits += 1
            return entry.value
        self.misses += 1
        started = time.perf_counter()
        value = self.origin.fetch(key)
        self._store(key, value, time.perf_counter() - started)
        return value


class JitteredTTL(NaiveTTL):
    """The same, with the expiry time spread so keys do not all turn over together.

    This is the standard advice and it is sound for the problem it solves, which is many
    keys expiring in lockstep because they were all populated at the same moment. It does
    nothing at all for one hot key, because a single key has a single expiry however it
    was chosen, and E3 is where that shows up.
    """

    name = "jittered"

    def __init__(self, origin: Origin, ttl_seconds: float, seed: int = 0,
                 jitter_share: float = 0.2) -> None:
        super().__init__(origin, ttl_seconds, seed)
        self.jitter_share = jitter_share

    def _ttl_for(self, key: str) -> float:
        spread = self.ttl_seconds * self.jitter_share
        return self.ttl_seconds + self.rng.uniform(-spread, spread)


class SingleFlight(Cache):
    """One reader recomputes, the rest wait for it.

    A per-key lock, taken only on a miss, with the entry re-checked after acquiring it.
    That second check is the whole mechanism: without it every reader that queued on the
    lock goes on to fetch anyway, having waited for the privilege.
    """

    name = "single_flight"

    def __init__(self, origin: Origin, ttl_seconds: float, seed: int = 0) -> None:
        super().__init__(origin, ttl_seconds, seed)
        self._keys: dict[str, threading.Lock] = {}
        self._keys_guard = threading.Lock()
        self.waited = 0

    def _key_lock(self, key: str) -> threading.Lock:
        with self._keys_guard:
            return self._keys.setdefault(key, threading.Lock())

    def get(self, key: str) -> str:
        entry = self._fresh(key)
        if entry is not None:
            self.hits += 1
            return entry.value

        lock = self._key_lock(key)
        contended = not lock.acquire(blocking=False)
        if contended:
            lock.acquire()
        try:
            entry = self._fresh(key)
            if entry is not None:
                # Somebody else did the work while this reader was queueing.
                self.hits += 1
                self.waited += 1
                return entry.value
            self.misses += 1
            started = time.perf_counter()
            value = self.origin.fetch(key)
            self._store(key, value, time.perf_counter() - started)
            return value
        finally:
            lock.release()


class EarlyRecompute(SingleFlight):
    """Refresh before the entry expires, while still serving the old value.

    The probability of choosing to refresh rises as the expiry approaches, scaled by how
    long the last recompute took, so an expensive key starts trying earlier. One reader
    refreshes and everyone else keeps being served the value that is about to expire, so
    there is never a moment with nothing to serve.

    The cost is staleness: readers are deliberately handed a value older than the one the
    origin would give. That is the trade, and E3 measures the size of it rather than
    assuming it is small.
    """

    name = "early_recompute"

    def __init__(self, origin: Origin, ttl_seconds: float, seed: int = 0,
                 beta: float = 1.0) -> None:
        super().__init__(origin, ttl_seconds, seed)
        self.beta = beta
        self.early_refreshes = 0
        self.stale_serves = 0

    def _should_refresh_early(self, entry: Entry) -> bool:
        remaining = entry.expires_at - time.perf_counter()
        if remaining <= 0:
            return True
        # The classic probabilistic early expiry: refresh when a draw scaled by the
        # recompute cost reaches into the time remaining.
        draw = -entry.computed_in * self.beta * self.rng.random()
        return remaining + draw <= 0

    def get(self, key: str) -> str:
        entry = self._fresh(key)
        if entry is not None and not self._should_refresh_early(entry):
            self.hits += 1
            return entry.value

        if entry is not None:
            # Still serveable. Try to become the one reader that refreshes it, and if
            # somebody else already is, hand back the old value rather than waiting.
            lock = self._key_lock(key)
            if lock.acquire(blocking=False):
                try:
                    self.early_refreshes += 1
                    self.misses += 1
                    started = time.perf_counter()
                    value = self.origin.fetch(key)
                    self._store(key, value, time.perf_counter() - started)
                    return value
                finally:
                    lock.release()
            self.hits += 1
            self.stale_serves += 1
            return entry.value

        return super().get(key)

    def as_dict(self) -> dict:
        return {**super().as_dict(), "early_refreshes": self.early_refreshes,
                "stale_serves": self.stale_serves}


def build(cache: str, origin: Origin, ttl_seconds: float, seed: int = 0,
          jitter_share: float = 0.2, beta: float = 1.0) -> Cache:
    if cache == "naive":
        return NaiveTTL(origin, ttl_seconds, seed)
    if cache == "jittered":
        return JitteredTTL(origin, ttl_seconds, seed, jitter_share)
    if cache == "single_flight":
        return SingleFlight(origin, ttl_seconds, seed)
    if cache == "early_recompute":
        return EarlyRecompute(origin, ttl_seconds, seed, beta)
    raise ValueError(f"unknown cache {cache!r}")
