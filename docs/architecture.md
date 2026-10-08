# Architecture

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

## Typing and validation

- The backend Protocols are `runtime_checkable`, so `isinstance(store, OnlineStoreProtocol)`
  is a real, meaningful check, not just documentation - see `redis_store.py`.
- `mypy skewproof` runs in CI on every push, and the codebase is fully type-hinted.
- Any dataclass field that gets interpolated into a string that isn't a bind
  parameter (SQL identifiers, for instance) is validated in `__post_init__` rather
  than trusted as-is - see `SqlEventSource` for the pattern. `table`,
  `entity_column`, `timestamp_column`, and `value_column` are SQL identifiers, not
  values, so they can't go through a parameterized placeholder the way `entity_id`
  and `max_ts` do.

## Logging, metrics, and health

The library itself never configures logging - every module that logs gets a plain
`logging.getLogger(__name__)` and leaves handlers and levels to the embedding
application, the standard library-author convention. Where it actually logs:

- `MaterializationJob.run()` logs a start/summary line and a warning per entity
  that comes back with an unknown value - see `materialize.py`.
- `skewproof.serve`'s `FeatureServer` logs every HTTP request (method, path,
  status, duration) at `INFO`, and any unhandled exception in a request at `ERROR`
  before turning it into a `500` response.

For an actual health and metrics surface (not just log lines an operator has to go
looking for), see **[Serving over HTTP](serving.md)**: `GET /healthz` for
liveness and `GET /metrics` for request and error counters in Prometheus text
format, hand-rolled rather than pulling in a metrics client library, consistent
with the project's zero-runtime-dependency design (see the comment above
`dependencies = []` in `pyproject.toml`).
