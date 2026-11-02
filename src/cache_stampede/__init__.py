"""Measure what a cache asks of its origin, as opposed to what its hit rate says.

A time to live is usually described as a knob that trades freshness for load. It is also,
and less obviously, a clock that tells every concurrent reader of a key to miss at exactly
the same moment.
"""

from cache_stampede.config import ConfigError, ScenarioConfig

__all__ = ["ScenarioConfig", "ConfigError"]
__version__ = "0.1.0"
