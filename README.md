# skewproof

Define a feature once. The same definition computes its value for training and for
serving, so the two can't fall out of sync.

Most feature pipelines write each feature twice: once in the training job over
historical data, and again in the serving code that runs at request time. The two
copies drift, and when they do, the model trains on one thing and predicts on
another. That gap is called training-serving skew, and most tools handle it by
watching for it after the fact. skewproof removes the second copy instead. If there
is only one implementation, there is nothing to drift.

## The idea

```python
from skewproof.definition import Aggregation, FeatureRegistry, feature

reg = FeatureRegistry()

soil = feature(
    reg,
    name="soil_moisture_latest",
    source="soil_readings",
    entity_key="farmer_id",
    timestamp_key="event_ts",
    value_key="moisture",
    aggregation=Aggregation.LATEST,
)

# rows: (event_ts, value) pairs for one entity
soil.reduce(rows, as_of=some_timestamp)
```

`reduce()` takes the time you care about as an argument. Training asks for the
value as of each historical label; serving asks for the value as of now. Same
function, so the answers agree by construction. The point-in-time filter
(`event_ts <= as_of`) lives inside `reduce()`, which is what stops a training set
from seeing values that didn't exist yet.

## Try it

```bash
pip install -e ".[dev]"
python -m skewproof.cli demo
```

You'll see the same feature computed two ways, point-in-time for training and from
the online store for serving, with the values matching. Change `--day` to watch the
point-in-time filter include or exclude a later reading.

## Working with your own features

Feature definitions live in a plain Python file exposing a module-level `registry`
(the same `FeatureRegistry` shown above) - there's no separate config file format to
learn. The CLI can list, validate, and materialize from one:

```bash
skewproof list --config features.py
skewproof validate --config features.py
skewproof materialize --config features.py --feature soil_moisture_latest \
  --source-path readings.csv --entities farm_a,farm_b --as-of 2026-01-08T00:00:00
```

`materialize` reads events from a CSV file and writes into an online store -
`--store memory` (default, doesn't persist) or `--store sqlite --store-path FILE`
(persists). It prints a `MaterializationReport` and exits non-zero if any entity's
value came back unknown.

## Develop

```bash
pip install -e ".[dev]"
pytest
```

The test run enforces 100% line and branch coverage and fails below it.

The Postgres and Redis integration tests are skipped unless you point them at running
services:

```bash
docker compose -f deploy/docker-compose.yml up -d
pip install -e ".[dev,postgres,redis]"
SKEWPROOF_PG_DSN=postgresql://skewproof:skewproof@localhost:5432/skewproof \
SKEWPROOF_REDIS_URL=redis://localhost:6379/0 \
pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full dev setup, what CI checks, and
style expectations. `.env.example` documents the two variables above if you'd rather
put them in a `.env` file than inline them per-command.

### Without installing Python locally

```bash
docker build -t skewproof .
docker run --rm skewproof
```

Or open the repo in VS Code with the Dev Containers extension for a preconfigured
Python 3.12 environment (`.devcontainer/devcontainer.json`).

## How it fits together

The offline path reads history from an `EventSource` (in-memory, CSV, or Postgres)
and builds point-in-time training sets. The online path serves materialized values
from an `OnlineStore` (in-memory, SQLite, or Redis). A materialization job syncs
offline to online and is safe to re-run. Every path computes values through one
`reduce()`, so training and serving cannot disagree.

Both sides are `Protocol`-typed, so a new backend only needs to satisfy `rows_for()`
(a source) or `materialize()`/`get()` (a store) - see `csv_source.py` and
`sqlite_store.py` for the smallest examples of each.

| Backend        | Kind         | Needs               | Good for                          |
|----------------|--------------|---------------------|------------------------------------|
| `InMemoryEventSource` / `OnlineStore` | source / store | nothing | tests, demos |
| `CsvEventSource`      | source | a file              | local dev, onboarding without a DB |
| `SqlEventSource`      | source | Postgres or SQLite  | production history                 |
| `SqliteOnlineStore`   | store  | a file (or none)    | single-process serving, durable, no server to run |
| `RedisOnlineStore`    | store  | Redis               | multi-process / networked serving  |

## License

MIT

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
