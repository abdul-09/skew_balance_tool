"""
A small command-line entry point.

main() takes argv and an output stream as arguments instead of reaching for sys.argv
and print() directly, so tests can drive it and capture output without subprocesses.
The __main__ block wires the real sys.argv/stdout to it.

Subcommands:
  demo    run the end-to-end define -> train -> materialize -> serve loop
  version print the package version
"""
from __future__ import annotations

import argparse
import io
import sys
from datetime import datetime

from . import __version__
from .demo import run_demo, ts


def _format_demo(as_of: datetime) -> str:
    result = run_demo(as_of)
    lines = [
        f"as_of: {result.as_of.isoformat()}",
        "training values (point-in-time):",
    ]
    for entity, value in result.training.items():
        lines.append(f"  {entity}: {value}")
    lines.append("served values (online store):")
    for entity, value in result.served.items():
        lines.append(f"  {entity}: {value}")
    lines.append(f"no skew (training == served): {result.no_skew}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="skewproof")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run the end-to-end demo")
    demo.add_argument(
        "--day",
        type=int,
        default=8,
        help="as_of day in January 2026 (default: 8)",
    )

    sub.add_parser("version", help="print the version")
    return parser


def main(argv: list[str], stdout: io.TextIOBase) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        stdout.write(f"{__version__}\n")
        return 0

    # Only "demo" remains; subparsers are required so nothing else reaches here.
    stdout.write(_format_demo(ts(args.day)) + "\n")
    return 0


def entrypoint() -> int:  # pragma: no cover
    return main(sys.argv[1:], sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(entrypoint())
