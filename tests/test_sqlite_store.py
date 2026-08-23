"""
Tests for the SQLite-backed online store.

Runs against a real sqlite3 connection (":memory:"), not a mock - sqlite3 is
already in the standard library, so there's no reason to fake it.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureDefinition, FeatureRegistry, feature
from skewproof.offline import InMemoryEventSource, OfflineStore, SpineRow
from skewproof.online import OnlineStore
from skewproof.redis_store import OnlineStoreProtocol
from skewproof.sqlite_store import SqliteOnlineStore


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


def latest(reg: FeatureRegistry, name: str = "soil_latest") -> FeatureDefinition:
    return feature(
        reg,
        name=name,
        source="readings",
        entity_key="farmer_id",
        timestamp_key="event_ts",
        value_key="moisture",
        aggregation=Aggregation.LATEST,
    )


class TestSqliteOnlineStore:
    def test_materialize_then_get(self, source, reg) -> None:
        store = SqliteOnlineStore()
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1", "f2"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0
        assert store.get("soil_latest", "f2") == 7.0

    def test_get_unmaterialized_returns_none(self, reg) -> None:
        store = SqliteOnlineStore()
        latest(reg)
        assert store.get("soil_latest", "f1") is None

    def test_materialized_none_returns_none(self, source, reg) -> None:
        store = SqliteOnlineStore()
        fdef = latest(reg)
        store.materialize(fdef, source, ["nobody"], ts(6))
        assert store.get("soil_latest", "nobody") is None

    def test_never_vs_materialized_none_are_distinct_in_storage(self, source, reg) -> None:
        store = SqliteOnlineStore()
        fdef = latest(reg)
        store.materialize(fdef, source, ["nobody"], ts(6))
        cur = store._conn.execute(
            "SELECT 1 FROM skewproof_features WHERE feature_name = ? AND entity_id = ?",
            ("soil_latest", "nobody"),
        )
        assert cur.fetchone() is not None
        cur = store._conn.execute(
            "SELECT 1 FROM skewproof_features WHERE feature_name = ? AND entity_id = ?",
            ("soil_latest", "ghost"),
        )
        assert cur.fetchone() is None

    def test_idempotent(self, source, reg) -> None:
        store = SqliteOnlineStore()
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1"], ts(6))
        first = store.get("soil_latest", "f1")
        store.materialize(fdef, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == first

    def test_rematerialize_at_later_as_of_updates(self, source, reg) -> None:
        store = SqliteOnlineStore()
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0
        store.materialize(fdef, source, ["f1"], ts(10))
        assert store.get("soil_latest", "f1") == 99.0

    def test_two_features_do_not_collide(self, source, reg) -> None:
        store = SqliteOnlineStore()
        f1 = latest(reg, "soil_latest")
        f2 = latest(reg, "soil_other")
        store.materialize(f1, source, ["f1"], ts(6))
        store.materialize(f2, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0
        assert store.get("soil_other", "f1") == 30.0

    def test_survives_across_connections_when_file_backed(self, tmp_path, reg) -> None:
        path = str(tmp_path / "features.db")
        fdef = latest(reg)
        writer = SqliteOnlineStore(path)
        writer.materialize(fdef, InMemoryEventSource(data={"f1": [(ts(1), 10.0)]}), ["f1"], ts(6))
        writer.close()

        reader = SqliteOnlineStore(path)
        assert reader.get("soil_latest", "f1") == 10.0
        reader.close()

    def test_context_manager_closes_connection(self, source, reg) -> None:
        fdef = latest(reg)
        with SqliteOnlineStore() as store:
            store.materialize(fdef, source, ["f1"], ts(6))
            assert store.get("soil_latest", "f1") == 30.0
        with pytest.raises(Exception):  # noqa: B017 - sqlite3.ProgrammingError on a closed conn
            store.get("soil_latest", "f1")


class TestSatisfiesProtocol:
    def test_satisfies_the_serving_protocol(self) -> None:
        assert isinstance(SqliteOnlineStore(), OnlineStoreProtocol)
        assert isinstance(OnlineStore(), OnlineStoreProtocol)


class TestNoSkewOverSqlite:
    """Offline training value equals the value served from the SQLite store."""

    def test_offline_equals_sqlite(self, source, reg) -> None:
        fdef = latest(reg)
        as_of = ts(6)
        entities = ["f1", "f2"]

        offline = OfflineStore(source)
        training = offline.build_training_set(fdef, [SpineRow(e, as_of) for e in entities])
        offline_vals = {r["entity_id"]: r["soil_latest"] for r in training}

        store = SqliteOnlineStore()
        store.materialize(fdef, source, entities, as_of)
        sqlite_vals = {e: store.get("soil_latest", e) for e in entities}

        assert offline_vals == sqlite_vals
