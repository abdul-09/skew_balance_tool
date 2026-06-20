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

## How it fits together

The offline path reads history from an `EventSource` (in-memory or Postgres) and
builds point-in-time training sets. The online path serves materialized values from
an `OnlineStore` (in-memory or Redis). A materialization job syncs offline to online
and is safe to re-run. Every path computes values through one `reduce()`, so training
and serving cannot disagree.

## License

MIT
