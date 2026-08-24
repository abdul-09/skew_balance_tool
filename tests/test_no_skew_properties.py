"""
Property-based fuzzing of the core "no skew" claim: for the same feature,
entity, and as_of, the offline (point-in-time training) value and the online
(materialized, served) value must always agree.

tests/test_online.py's TestNoSkew and the various test_*_store.py
TestNoSkewOver* classes check this against a handful of handwritten scenarios.
This file generates a wide random space of (event history, aggregation, window,
as_of, entity subset) combinations per run and checks the same equality on
every one, against every in-process store implementation - this is the
property the whole project exists to guarantee, so it gets the widest net.

Postgres and Redis aren't included here: they need a live service (see
tests/test_sql_source.py and tests/test_redis_store.py's SKEWPROOF_PG_DSN /
SKEWPROOF_REDIS_URL - gated integration tests), which doesn't fit a fuzz run
meant to execute on every push. OnlineStore and SqliteOnlineStore both compute
values by calling reduce() directly (see their materialize() methods), the same
independent-implementation pattern the excluded two follow, so fuzzing these
two is a meaningful proxy for the property those tests check with live services.
"""
from __future__ import annotations

from datetime import datetime

from hypothesis import given, settings
from hypothesis import strategies as st

from skewproof.definition import Aggregation, FeatureDefinition
from skewproof.offline import InMemoryEventSource, OfflineStore, SpineRow
from skewproof.online import OnlineStore
from skewproof.sqlite_store import SqliteOnlineStore

_ENTITY_IDS = ["e1", "e2", "e3"]
_datetimes = st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2035, 1, 1))
_values = st.floats(
    allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6, width=32
)
_rows = st.lists(st.tuples(_datetimes, _values), max_size=15)
_aggregations = st.sampled_from(list(Aggregation))
_window_seconds = st.one_of(st.none(), st.integers(min_value=1, max_value=10_000_000))
_entity_data = st.fixed_dictionaries({entity: _rows for entity in _ENTITY_IDS})
_entity_subset = st.lists(st.sampled_from(_ENTITY_IDS), min_size=1, max_size=3, unique=True)


_EntityData = dict[str, list[tuple[datetime, float]]]


@st.composite
def _entity_data_and_as_of(draw: st.DrawFn) -> tuple[_EntityData, datetime]:
    """Pairs entity data with an as_of that's independent most of the time, but
    anchored close to a real event timestamp the rest of the time.

    A purely independent as_of drawn from the full ~35-year range almost never
    lands within seconds or days of an actual row - so a small timing bug (an
    off-by-a-few-seconds skew between the offline and online path, say) would
    almost never change which rows are visible, and the property test would
    pass on a genuinely broken implementation. Anchoring as_of near real
    timestamps some of the time makes boundary-adjacent cases common instead of
    astronomically rare, which is exactly where a skew bug would actually show
    up as a different set of visible rows.
    """
    data = draw(_entity_data)
    timestamps = [ts for rows in data.values() for ts, _ in rows]
    if timestamps and draw(st.booleans()):
        anchor = draw(st.sampled_from(timestamps))
        delta_seconds = draw(st.integers(min_value=-864_000, max_value=864_000))  # +/- 10 days
        as_of = datetime.fromtimestamp(anchor.timestamp() + delta_seconds)
    else:
        as_of = draw(_datetimes)
    return data, as_of


def _run_offline(
    source: InMemoryEventSource, definition: FeatureDefinition,
    entities: list[str], as_of: datetime,
) -> dict[str, float | None]:
    offline = OfflineStore(source)
    training = offline.build_training_set(
        definition, [SpineRow(e, as_of) for e in entities]
    )
    return {row["entity_id"]: row[definition.name] for row in training}


class TestNoSkewFuzzedOverOnlineStore:
    @settings(max_examples=150)
    @given(
        data_and_as_of=_entity_data_and_as_of(), agg=_aggregations,
        window=_window_seconds, entities=_entity_subset,
    )
    def test_offline_and_in_memory_online_always_agree(
        self, data_and_as_of, agg, window, entities
    ) -> None:
        data, as_of = data_and_as_of
        source = InMemoryEventSource(data=data)
        definition = FeatureDefinition(
            name="f", source="s", entity_key="e", timestamp_key="t", value_key="v",
            aggregation=agg, window_seconds=window,
        )

        offline_vals = _run_offline(source, definition, entities, as_of)

        online = OnlineStore()
        online.materialize(definition, source, entities, as_of)
        online_vals = {e: online.get("f", e) for e in entities}

        assert offline_vals == online_vals


class TestNoSkewFuzzedOverSqliteStore:
    @settings(max_examples=150)
    @given(
        data_and_as_of=_entity_data_and_as_of(), agg=_aggregations,
        window=_window_seconds, entities=_entity_subset,
    )
    def test_offline_and_sqlite_online_always_agree(
        self, data_and_as_of, agg, window, entities
    ) -> None:
        data, as_of = data_and_as_of
        source = InMemoryEventSource(data=data)
        definition = FeatureDefinition(
            name="f", source="s", entity_key="e", timestamp_key="t", value_key="v",
            aggregation=agg, window_seconds=window,
        )

        offline_vals = _run_offline(source, definition, entities, as_of)

        online = SqliteOnlineStore()
        try:
            online.materialize(definition, source, entities, as_of)
            online_vals = {e: online.get("f", e) for e in entities}
        finally:
            online.close()

        assert offline_vals == online_vals
