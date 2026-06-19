"""
Tests for the online path and the headline claim: for the same (entity, as_of), the
offline training value equals the online served value, because both go through the
same reduce().
"""
from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureDefinition, FeatureRegistry, feature
from skewproof.offline import InMemoryEventSource, OfflineStore, SpineRow
from skewproof.online import OnlineStore


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


@pytest.fixture
def source() -> InMemoryEventSource:
    return InMemoryEventSource(
        data={
            "f1": [(ts(1), 10.0), (ts(3), 20.0), (ts(5), 30.0), (ts(9), 99.0)],
            "f2": [(ts(2), 5.0), (ts(4), 7.0)],
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


class TestOnlineStore:
    def test_materialize_then_get(self, source, reg) -> None:
        online = OnlineStore()
        fdef = latest(reg, "soil_latest")
        online.materialize(fdef, source, ["f1", "f2"], ts(6))
        assert online.get("soil_latest", "f1") == 30.0
        assert online.get("soil_latest", "f2") == 7.0

    def test_get_unmaterialized_returns_none(self, reg) -> None:
        online = OnlineStore()
        latest(reg, "soil_latest")
        assert online.get("soil_latest", "f1") is None

    def test_missing_entity_materializes_none(self, source, reg) -> None:
        online = OnlineStore()
        fdef = latest(reg, "soil_latest")
        online.materialize(fdef, source, ["nobody"], ts(6))
        assert online.get("soil_latest", "nobody") is None

    def test_materialize_is_idempotent(self, source, reg) -> None:
        online = OnlineStore()
        fdef = latest(reg, "soil_latest")
        online.materialize(fdef, source, ["f1"], ts(6))
        first = online.get("soil_latest", "f1")
        online.materialize(fdef, source, ["f1"], ts(6))
        assert online.get("soil_latest", "f1") == first

    def test_rematerialize_at_later_as_of_updates_value(self, source, reg) -> None:
        online = OnlineStore()
        fdef = latest(reg, "soil_latest")
        online.materialize(fdef, source, ["f1"], ts(6))
        assert online.get("soil_latest", "f1") == 30.0
        online.materialize(fdef, source, ["f1"], ts(10))
        assert online.get("soil_latest", "f1") == 99.0

    def test_keys_are_namespaced_by_feature(self, source, reg) -> None:
        online = OnlineStore()
        a = latest(reg, "feat_a")
        b = latest(reg, "feat_b")
        online.materialize(a, source, ["f1"], ts(2))   # latest at day2 -> 10.0
        online.materialize(b, source, ["f1"], ts(6))   # latest at day6 -> 30.0
        assert online.get("feat_a", "f1") == 10.0
        assert online.get("feat_b", "f1") == 30.0


class TestNoSkew:
    """The headline claim, as a runnable assertion."""

    def test_offline_equals_online_for_same_as_of(self, source, reg) -> None:
        fdef = latest(reg, "soil_latest")
        as_of = ts(6)
        entities = ["f1", "f2"]

        offline = OfflineStore(source)
        training = offline.build_training_set(
            fdef, [SpineRow(e, as_of) for e in entities]
        )
        offline_vals = {r["entity_id"]: r["soil_latest"] for r in training}

        online = OnlineStore()
        online.materialize(fdef, source, entities, as_of)
        online_vals = {e: online.get("soil_latest", e) for e in entities}

        assert offline_vals == online_vals

    def test_paths_agree_across_many_as_of(self, source, reg) -> None:
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
        offline = OfflineStore(source)
        for day in (2, 4, 6, 8, 10):
            as_of = ts(day)
            [off] = offline.build_training_set(fdef, [SpineRow("f1", as_of)])
            online = OnlineStore()
            online.materialize(fdef, source, ["f1"], as_of)
            assert off["soil_3d_sum"] == online.get("soil_3d_sum", "f1")
