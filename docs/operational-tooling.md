# Operational tooling

Beyond materializing one feature for one `as_of`, three building blocks for
running this in practice. Only `doctor` has CLI wiring - the others need a
source-and-entities-per-feature shape that doesn't compress well into flags, so a
short Python script is the natural fit, the same way `demo.py` is.

## Batch materialization

`skewproof.batch.BatchMaterializationJob` materializes several features - a whole
registry, or a chosen subset - against one online store in a single call, each
with its own `EventSource` (a `{feature_name: source}` mapping, since two
features rarely share the exact same table or file).

```python
from skewproof.batch import BatchMaterializationJob

batch = BatchMaterializationJob(online_store)
report = batch.run(
    registry,
    sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
    entity_ids=["farm_a", "farm_b"],
    as_of=as_of,
)
report.is_complete       # True if every feature in the batch was complete
report.feature_names     # ("soil_moisture", "rainfall")
```

It fails before writing anything if a requested feature has no source (or, when
`entity_ids` is a per-feature `dict`, no entity list). Silently skipping a
feature you meant to materialize is the kind of thing that turns into an
incident days later.

## Backfill

`skewproof.backfill.BackfillJob` replays one feature across a range of `as_of`
instants.

```python
from skewproof.backfill import BackfillJob, daily_range

job = BackfillJob(online_store, source)
report = job.run(definition, entity_ids, daily_range(start, end))
report.incomplete_steps()   # the as_of values where some entity was unknown
```

Every online store here holds one current value per (feature, entity) - there's
no multi-snapshot history in the store itself. So after a backfill, only the last
`as_of`'s values are what's actually served; the earlier steps aren't retained
anywhere except in the `BackfillReport` this returns. Still useful for two real
things:

- **Incremental population.** Materializing straight to a far-future `as_of` in
  one call is one big, all-or-nothing write. Backfilling day by day up to that
  same `as_of` reaches the same end state, but a crash partway through leaves the
  store at a valid earlier `as_of` instead of a half-written one.
- **Historical audit.** Walking `as_of` through history and checking each step's
  `values_unknown` via `incomplete_steps()` is how you'd notice that coverage for
  a feature was fine until three weeks ago - a gap a single `as_of='now'`
  materialization would never surface.

## `skewproof doctor`

Checks whether `SKEWPROOF_PG_DSN`/`SKEWPROOF_REDIS_URL` are set and, if so,
whether the corresponding client library is installed and can actually connect.
See the [CLI reference](cli.md#skewproof-doctor).
