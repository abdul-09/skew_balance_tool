"""
The end-to-end demo, as a function that returns a structured result.

It runs the whole loop in-process over seed data: define a feature once, build a
point-in-time training set from history, materialize the same feature into the online
store, then serve it. The point of returning a result object (rather than only
printing) is that the demo is itself testable: we assert the training value and the
served value agree, which is the no-skew property demonstrated end to end.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .definition import Aggregation, FeatureRegistry, feature
from .materialize import MaterializationJob
from .offline import InMemoryEventSource, OfflineStore, SpineRow
from .online import OnlineStore


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


def seed_source() -> InMemoryEventSource:
    """A small, fixed history for two farms."""
    return InMemoryEventSource(
        data={
            "farm_a": [(ts(1), 12.0), (ts(4), 18.0), (ts(7), 25.0), (ts(11), 40.0)],
            "farm_b": [(ts(2), 8.0), (ts(6), 15.0)],
        }
    )


@dataclass(frozen=True)
class DemoResult:
    as_of: datetime
    training: dict[str, float | None]   # entity -> point-in-time training value
    served: dict[str, float | None]     # entity -> value served from online store
    no_skew: bool                       # training == served for every entity


def run_demo(as_of: datetime | None = None) -> DemoResult:
    as_of = as_of or ts(8)
    source = seed_source()
    entities = ["farm_a", "farm_b"]

    reg = FeatureRegistry()
    fdef = feature(
        reg,
        name="soil_latest",
        source="soil_readings",
        entity_key="farm_id",
        timestamp_key="event_ts",
        value_key="moisture",
        aggregation=Aggregation.LATEST,
    )

    # Offline: point-in-time training values as of `as_of`.
    offline = OfflineStore(source)
    training_rows = offline.build_training_set(
        fdef, [SpineRow(e, as_of) for e in entities]
    )
    training = {r["entity_id"]: r["soil_latest"] for r in training_rows}

    # Online: materialize the same feature, then serve.
    online = OnlineStore()
    MaterializationJob(online, source).run(fdef, entities, as_of)
    served = {e: online.get("soil_latest", e) for e in entities}

    return DemoResult(
        as_of=as_of,
        training=training,
        served=served,
        no_skew=training == served,
    )
