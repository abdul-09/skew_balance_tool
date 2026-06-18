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

## Develop

```bash
pip install -e ".[dev]"
pytest
```

The test run enforces 100% line and branch coverage and fails below it.

## Status

First commit: the core definition and the project skeleton. The training and
serving stores, the Postgres and Redis backends, and the end-to-end demo land in
later commits. The model is tested on its own before any storage exists.

## License

MIT
