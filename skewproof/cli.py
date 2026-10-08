"""
A small command-line entry point.

main() takes argv and an output stream as arguments instead of reaching for sys.argv
and print() directly, so tests can drive it and capture output without subprocesses.
The __main__ block wires the real sys.argv/stdout to it.

Subcommands:
  demo         run the end-to-end define -> train -> materialize -> serve loop
  version      print the package version
  list         list the features defined in a config file
  validate     load a config file and report whether it's valid
  materialize  run a MaterializationJob for one feature from a config file
  doctor       check connectivity for the optional Postgres/Redis backends
  serve        serve materialized features over HTTP

list/validate/materialize/serve all take --config, a path to a Python file
exposing a module-level `registry` FeatureRegistry (see
skewproof.config.load_registry).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import TextIO

from . import __version__
from .config import ConfigError, load_registry
from .csv_source import CsvEventSource
from .demo import run_demo, ts
from .doctor import CheckResult, run_doctor
from .materialize import MaterializationJob, MaterializationReport
from .online import OnlineStore
from .serve import run_server
from .sqlite_store import SqliteOnlineStore


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


def _format_report(report: MaterializationReport) -> str:
    lines = [
        f"feature: {report.feature_name}",
        f"as_of: {report.as_of.isoformat()}",
        f"entities processed: {report.entities_processed}",
        f"values written: {report.values_written}",
        f"values unknown: {report.values_unknown}",
        f"complete: {report.is_complete}",
    ]
    return "\n".join(lines)


def _format_check(result: CheckResult) -> str:
    symbol = {"ok": "OK", "not_configured": "--", "failed": "FAIL"}[result.status]
    return f"[{symbol}] {result.name}: {result.detail}"


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

    list_cmd = sub.add_parser("list", help="list the features in a config file")
    list_cmd.add_argument("--config", required=True, help="path to a Python config file")

    validate = sub.add_parser("validate", help="validate a config file")
    validate.add_argument("--config", required=True, help="path to a Python config file")

    materialize = sub.add_parser(
        "materialize", help="materialize one feature from a CSV source into a store"
    )
    materialize.add_argument("--config", required=True, help="path to a Python config file")
    materialize.add_argument("--feature", required=True, help="feature name to materialize")
    materialize.add_argument(
        "--source-path", required=True, help="CSV file to read events from"
    )
    materialize.add_argument(
        "--store",
        choices=["memory", "sqlite"],
        default="memory",
        help="online store backend (default: memory)",
    )
    materialize.add_argument(
        "--store-path",
        default=":memory:",
        help="sqlite store file path (default: in-memory, only meaningful with --store sqlite)",
    )
    materialize.add_argument(
        "--entities", required=True, help="comma-separated entity ids to materialize"
    )
    materialize.add_argument(
        "--as-of", required=True, help="ISO 8601 timestamp, e.g. 2026-01-08T00:00:00"
    )

    sub.add_parser(
        "doctor", help="check connectivity for the optional Postgres/Redis backends"
    )

    serve = sub.add_parser("serve", help="serve materialized features over HTTP")
    serve.add_argument("--config", required=True, help="path to a Python config file")
    serve.add_argument(
        "--store",
        choices=["memory", "sqlite"],
        default="memory",
        help="online store backend to serve from (default: memory, empty until you "
        "materialize into it separately - sqlite is the usual choice here)",
    )
    serve.add_argument(
        "--store-path",
        default=":memory:",
        help="sqlite store file path (only meaningful with --store sqlite)",
    )
    serve.add_argument("--host", default="127.0.0.1", help="bind host (default: 127.0.0.1)")
    serve.add_argument("--port", type=int, default=8000, help="bind port (default: 8000)")

    return parser


def _cmd_list(args: argparse.Namespace, stdout: TextIO) -> int:
    try:
        registry = load_registry(args.config)
    except ConfigError as exc:
        stdout.write(f"error: {exc}\n")
        return 1

    definitions = sorted(registry.all(), key=lambda d: d.name)
    if not definitions:
        stdout.write("(no features registered)\n")
        return 0
    for d in definitions:
        window = f"{d.window_seconds}s" if d.window_seconds is not None else "all history"
        stdout.write(f"{d.name}  source={d.source}  agg={d.aggregation.value}  window={window}\n")
    return 0


def _cmd_validate(args: argparse.Namespace, stdout: TextIO) -> int:
    try:
        registry = load_registry(args.config)
    except ConfigError as exc:
        stdout.write(f"invalid: {exc}\n")
        return 1
    stdout.write(f"OK: {len(registry.all())} feature(s) valid\n")
    return 0


def _cmd_materialize(args: argparse.Namespace, stdout: TextIO) -> int:
    try:
        registry = load_registry(args.config)
        definition = registry.get(args.feature)
    except (ConfigError, KeyError) as exc:
        stdout.write(f"error: {exc}\n")
        return 1

    source = CsvEventSource(
        path=args.source_path,
        entity_column=definition.entity_key,
        timestamp_column=definition.timestamp_key,
        value_column=definition.value_key,
    )
    store = SqliteOnlineStore(args.store_path) if args.store == "sqlite" else OnlineStore()
    entity_ids = [e.strip() for e in args.entities.split(",") if e.strip()]

    try:
        as_of = datetime.fromisoformat(args.as_of)
    except ValueError as exc:
        stdout.write(f"error: invalid --as-of {args.as_of!r}: {exc}\n")
        return 1

    job = MaterializationJob(store, source)
    report = job.run(definition, entity_ids, as_of)
    stdout.write(_format_report(report) + "\n")
    return 0 if report.is_complete else 1


def _cmd_doctor(stdout: TextIO) -> int:
    results = run_doctor()
    for result in results:
        stdout.write(_format_check(result) + "\n")
    return 0 if all(r.ok for r in results) else 1


def _cmd_serve(args: argparse.Namespace, stdout: TextIO) -> int:
    try:
        registry = load_registry(args.config)
    except ConfigError as exc:
        stdout.write(f"error: {exc}\n")
        return 1
    store = SqliteOnlineStore(args.store_path) if args.store == "sqlite" else OnlineStore()
    stdout.write(f"serving on http://{args.host}:{args.port} (Ctrl+C to stop)\n")
    run_server(store, registry, host=args.host, port=args.port)
    return 0


def main(argv: list[str], stdout: TextIO) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        stdout.write(f"{__version__}\n")
        return 0
    if args.command == "list":
        return _cmd_list(args, stdout)
    if args.command == "validate":
        return _cmd_validate(args, stdout)
    if args.command == "materialize":
        return _cmd_materialize(args, stdout)
    if args.command == "doctor":
        return _cmd_doctor(stdout)
    if args.command == "serve":
        return _cmd_serve(args, stdout)

    # Only "demo" remains; subparsers are required so nothing else reaches here.
    stdout.write(_format_demo(ts(args.day)) + "\n")
    return 0


def entrypoint() -> int:  # pragma: no cover
    return main(sys.argv[1:], sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(entrypoint())
