# Serving over HTTP

`skewproof.serve` is a minimal HTTP layer for reading materialized feature
values, with the observability the library was missing: a health check, request
counters, and structured per-request logging.

```bash
skewproof serve --config features.py --store sqlite --store-path features.db
```

or, embedded directly:

```python
from skewproof.serve import run_server
from skewproof.sqlite_store import SqliteOnlineStore

run_server(SqliteOnlineStore("features.db"), registry, host="0.0.0.0", port=8000)
```

## Endpoints

### `GET /healthz`

Liveness check: the process is up and answering requests.

```json
{"status": "ok"}
```

### `GET /metrics`

Request and error counters plus uptime, in Prometheus text-exposition format
(hand-rolled, not a metrics client library - see the
[architecture page](architecture.md#logging-metrics-and-health) for why):

```
# HELP skewproof_requests_total Total HTTP requests served.
# TYPE skewproof_requests_total counter
skewproof_requests_total 42
# HELP skewproof_errors_total Total HTTP requests with a 4xx/5xx response.
# TYPE skewproof_errors_total counter
skewproof_errors_total 3
# HELP skewproof_uptime_seconds Seconds since the server started.
# TYPE skewproof_uptime_seconds gauge
skewproof_uptime_seconds 128.41
```

### `GET /features/<name>/<entity_id>`

```json
{"feature": "soil_latest", "entity_id": "farm_a", "value": 30.0}
```

`value` is `null` when the store has no value for that (feature, entity) - either
it hasn't been materialized yet, or it was materialized as unknown. The store
protocol doesn't distinguish the two (see `OnlineStoreProtocol.get()`), so
neither does this endpoint. If a `registry` was passed to `build_server()` or
`run_server()`, a feature name that isn't registered is a `404` instead of a
`null` value, since that's almost always a typo rather than a genuinely
unmaterialized feature. Without a registry, any name is accepted as-is.

## What this is not

Single-threaded (`http.server.HTTPServer`, not `ThreadingHTTPServer`): requests
are handled one at a time. That's the right tradeoff for local use, a demo, or a
small internal deployment. It is not meant for high-throughput production
serving. `RedisOnlineStore` behind a real application server is the answer
there; `FeatureServer` (the routing and response logic, with no socket code in
it) is reusable in front of it if you want the same endpoints.
