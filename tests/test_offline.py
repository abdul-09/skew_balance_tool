"""Tests for the offline path: point-in-time training sets and leakage prevention."""
from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureDefinition, FeatureRegistry, feature
from skewproof.offline import (
    InMemoryEventSource,
    OfflineStore,
    SpineRow,
)


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


@pytest.fixture
def source() -> InMemoryEventSource:
    return InMemoryEventSource(
        data={
            "f1": [
                (ts(1), 10.0),
                (ts(3), 20.0),
                (ts(5), 30.0),
                (ts(9), 99.0),  # future relative to as_of = day 6
            ],
            "f2": [
                (ts(2), 5.0),
                (ts(4), 7.0),
            ],
        }
    )


@pytest.fixture
def reg() -> FeatureRegistry:
    return FeatureRegistry()


def latest(reg: FeatureRegistry, name: str) -> FeatureDefinition:
    return feature(
        reg,
        name=name,
        source="readings",
        entity_key="farmer_id",
        timestamp_key="event_ts",
        value_key="moisture",
        aggregation=Aggregation.LATEST,
    )


class TestInMemoryEventSource:
    def test_returns_rows_for_known_entity(self, source: InMemoryEventSource) -> None:
        assert source.rows_for("f2") == [(ts(2), 5.0), (ts(4), 7.0)]

    def test_returns_empty_for_unknown_entity(self, source: InMemoryEventSource) -> None:
        assert source.rows_for("nobody") == []

    def test_returns_a_copy_not_the_internal_list(self, source: InMemoryEventSource) -> None:
        rows = source.rows_for("f1")
        rows.append((ts(20), 1.0))
        assert len(source.rows_for("f1")) == 4  # original untouched


class TestTrainingSet:
    def test_value_per_entity_at_as_of(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        spine = [SpineRow("f1", ts(6)), SpineRow("f2", ts(6))]
        rows = store.build_training_set(fdef, spine)
        by_entity = {r["entity_id"]: r["soil_latest"] for r in rows}
        assert by_entity == {"f1": 30.0, "f2": 7.0}

    def test_row_shape(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        [row] = store.build_training_set(fdef, [SpineRow("f1", ts(6))])
        assert set(row.keys()) == {"entity_id", "as_of", "soil_latest"}
        assert row["entity_id"] == "f1"
        assert row["as_of"] == ts(6)

    def test_missing_entity_value_is_none(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        [row] = store.build_training_set(fdef, [SpineRow("nobody", ts(6))])
        assert row["soil_latest"] is None

    def test_empty_spine_returns_empty(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        assert store.build_training_set(fdef, []) == []

    def test_same_entity_different_as_of_gives_different_values(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        spine = [SpineRow("f1", ts(2)), SpineRow("f1", ts(6)), SpineRow("f1", ts(10))]
        values = [r["soil_latest"] for r in store.build_training_set(fdef, spine)]
        assert values == [10.0, 30.0, 99.0]


class TestLeakageTrap:
    """A future event must never appear in a training row labeled before it."""

    def test_future_event_is_refused(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        # f1 has a day-9 reading of 99.0. A label at day 6 must not see it.
        [row6] = store.build_training_set(fdef, [SpineRow("f1", ts(6))])
        assert row6["soil_latest"] == 30.0
        assert row6["soil_latest"] != 99.0

    def test_event_becomes_visible_once_in_the_past(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = latest(reg, "soil_latest")
        # At day 10 the day-9 reading is legitimately historical.
        [row10] = store.build_training_set(fdef, [SpineRow("f1", ts(10))])
        assert row10["soil_latest"] == 99.0

    def test_windowed_feature_respects_as_of(self, source, reg) -> None:
        store = OfflineStore(source)
        fdef = feature(
            reg,
            name="soil_3d_sum",
            source="readings",
            entity_key="farmer_id",
            timestamp_key="event_ts",
            value_key="moisture",
            aggregation=Aggregation.SUM,
            window_seconds=3 * 24 * 3600,
        )
        # day 6, window [day3, day6]: day3(20) + day5(30) = 50; day9(99) is future.
        [row] = store.build_training_set(fdef, [SpineRow("f1", ts(6))])
        assert row["soil_3d_sum"] == 50.0
