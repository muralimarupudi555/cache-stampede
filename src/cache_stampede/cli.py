"""Command line entry point.

Exit code 4 is the one worth having. It does not say the cache is missing too often, which
the hit rate would already say and which is usually false. It says that when the key did
expire, everybody missed at once, and the origin took the whole arrival rate for as long as
it took to answer.

Exit code 5 protects the rest. A saturated worker pool caps the stampede at the pool size,
and a measured cluster that misses the arithmetic means the run is not describing what it
claims, so no figure is printed.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from cache_stampede.config import CACHES, ConfigError, ScenarioConfig
from cache_stampede.report import Report, build_report

EXIT_COALESCED = 0
EXIT_BAD_CONFIG = 2
EXIT_INTERNAL_ERROR = 3
EXIT_STAMPEDE = 4
EXIT_MEASUREMENT_INVALID = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cache-stampede",
        description="Measure what a cache asks of its origin, not what its hit rate says.",
    )
    parser.add_argument("--cache", choices=CACHES, default="naive")
    parser.add_argument("--ttl-seconds", type=float, default=0.5)
    parser.add_argument("--origin-seconds", type=float, default=0.05)
    parser.add_argument("--request-rate", type=float, default=200.0)
    parser.add_argument("--duration-seconds", type=float, default=3.0)
    parser.add_argument("--jitter-share", type=float, default=0.2)
    parser.add_argument("--early-beta", type=float, default=1.0)
    parser.add_argument("--keys", type=int, default=1)
    parser.add_argument("--prefill", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def classify(report: Report) -> int:
    if not report.measurement_valid:
        return EXIT_MEASUREMENT_INVALID
    if report.stampeding:
        return EXIT_STAMPEDE
    return EXIT_COALESCED


def render(report: Report) -> str:
    config, result = report.config, report.result
    lines = [
        f"{config.cache}, ttl {config.ttl_seconds:g}s, origin "
        f"{config.origin_seconds * 1000:.0f}ms, {config.request_rate:g} requests/s, "
        f"{config.keys} key{'s' if config.keys > 1 else ''}",
        "",
        f"{'reading':<36}{'measured':>10}{'derived':>10}",
        "-" * 56,
        f"{'origin calls per refresh':<36}{result.typical_stampede:>10.1f}"
        f"{report.predicted_stampede:>10}",
        f"{'worst refresh observed':<36}{result.stampede_size:>10}",
        f"{'peak simultaneous origin calls':<36}{result.peak_concurrency:>10}",
        f"{'origin calls in total':<36}{result.origin_calls:>10}",
        "-" * 56,
        f"{'hit rate':<36}{result.hit_rate:>9.2%}"
        f"{report.predicted_hit_rate:>10.2%}",
        f"{'requests made to wait':<36}{result.stalled_share:>9.2%}",
        f"{'p99 response':<36}{result.latency_p99_ms:>8.1f} ms",
    ]
    extras = result.as_dict()
    if "stale_serves" in extras:
        lines.append(f"{'values served while refreshing':<36}"
                     f"{extras['stale_serves']:>10}")
    if report.stampeding:
        lines += [
            "",
            f"when the key expired, {result.typical_stampede:.0f} requests reached the "
            f"origin at once and it peaked at {result.peak_concurrency} simultaneous "
            "calls.",
            f"The hit rate for the same run was {result.hit_rate:.2%}. Nothing on a "
            "cache dashboard distinguishes this from a cache that is working.",
        ]
    if not report.measurement_valid:
        lines.append("")
        if result.pool_saturated:
            lines.append(
                f"the harness ran out of workers ({result.peak_in_flight} in flight "
                f"against a pool of {result.pool_size}), which caps the stampede at the "
                "pool size and makes this a measurement of the harness"
            )
        else:
            lines.append(
                f"measured {result.typical_stampede:.1f} calls per refresh against a "
                f"derived {report.predicted_stampede}: this run is not describing what "
                "it claims to"
            )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = ScenarioConfig(
            cache=args.cache, ttl_seconds=args.ttl_seconds,
            origin_seconds=args.origin_seconds, request_rate=args.request_rate,
            duration_seconds=args.duration_seconds, jitter_share=args.jitter_share,
            early_beta=args.early_beta, keys=args.keys, prefill=args.prefill,
        )
    except ConfigError as exc:
        print(f"invalid scenario: {exc}", file=sys.stderr)
        return EXIT_BAD_CONFIG

    try:
        report = build_report(config)
    except Exception as exc:  # noqa: BLE001
        print(f"run failed to complete: {exc}", file=sys.stderr)
        return EXIT_INTERNAL_ERROR

    print(json.dumps(report.as_dict(), indent=2) if args.json else render(report))
    return classify(report)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
