# Getting started

## Install

```bash
pip install -e ".[dev]"
```

`requirements/dev.txt` is a pinned, committed lockfile. To install the exact
versions CI tests against instead of whatever resolves today:

```bash
pip install -r requirements/dev.txt
pip install -e . --no-deps
```

## Run the demo

```bash
python -m skewproof.cli demo
```

You'll see the same feature computed two ways, point-in-time for training and from
the online store for serving, with the values matching. Change `--day` to watch the
point-in-time filter include or exclude a later reading.

## Without installing Python locally

```bash
docker build -t skewproof .
docker run --rm skewproof
```

Or open the repo in VS Code with the Dev Containers extension for a preconfigured
Python 3.12 environment (`.devcontainer/devcontainer.json`).

## Working with your own features

Feature definitions live in a plain Python file exposing a module-level `registry`
(the same `FeatureRegistry` from the [home page](index.md)) - there's no separate
config file format to learn. The CLI can list, validate, and materialize from one -
see the [CLI reference](cli.md) for the full command set.

```bash
skewproof list --config features.py
skewproof validate --config features.py
skewproof materialize --config features.py --feature soil_moisture_latest \
  --source-path readings.csv --entities farm_a,farm_b --as-of 2026-01-08T00:00:00
```

## Integration tests against real Postgres/Redis

The Postgres and Redis tests are skipped unless you point them at running services:

```bash
docker compose -f deploy/docker-compose.yml up -d
pip install -e ".[dev,postgres,redis]"
SKEWPROOF_PG_DSN=postgresql://skewproof:skewproof@localhost:5432/skewproof \
SKEWPROOF_REDIS_URL=redis://localhost:6379/0 \
pytest
```

`.env.example` documents the two variables above if you'd rather put them in a
`.env` file than inline them per-command. `skewproof doctor` checks whether
they're set and whether the corresponding backend is actually reachable.
