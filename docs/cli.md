# CLI reference

`list`, `validate`, `materialize`, and `serve` all take `--config`, a path to a
Python file exposing a module-level `registry` (a `FeatureRegistry`) - see
[Getting started](getting-started.md). There's no separate config file format;
the CLI loads it the same way Python would import it
(`skewproof.config.load_registry`).

## `skewproof demo`

Runs the end-to-end define, train, materialize, serve loop with seeded data.

```bash
skewproof demo --day 8
```

## `skewproof version`

Prints the installed package version.

## `skewproof list --config FILE`

Lists every feature in the registry: name, source, aggregation, and window.

## `skewproof validate --config FILE`

Loads the config and reports `OK: N feature(s) valid`, or the specific error
(missing file, syntax error, invalid definition, duplicate name) with a non-zero
exit code.

## `skewproof materialize`

```bash
skewproof materialize --config features.py --feature soil_latest \
  --source-path readings.csv \
  --store sqlite --store-path features.db \
  --entities farm_a,farm_b \
  --as-of 2026-01-08T00:00:00
```

Builds a `CsvEventSource` from `--source-path` using the feature's own
`entity_key`/`timestamp_key`/`value_key`, runs a `MaterializationJob`, and prints
the resulting `MaterializationReport`. `--store` is `memory` (default, doesn't
persist) or `sqlite` (persists to `--store-path`). Exits non-zero if any entity's
value came back unknown, so it's scriptable in CI or cron, not just a demo.

## `skewproof doctor`

```bash
skewproof doctor
```

Checks `SKEWPROOF_PG_DSN`/`SKEWPROOF_REDIS_URL`: unset is reported but not an
error, set-and-working is `OK`, set-and-broken (client library missing, or a
connection failure) is `FAIL` and the command exits non-zero.

## `skewproof serve`

```bash
skewproof serve --config features.py --store sqlite --store-path features.db \
  --host 0.0.0.0 --port 8000
```

Serves whatever is already in the given store over HTTP until interrupted
(Ctrl+C). It doesn't materialize anything itself, so run `materialize` (or a
[`BatchMaterializationJob`](operational-tooling.md)) against the same store path
first. See [Serving over HTTP](serving.md) for the endpoints.
