"""
Tests for the Redis-backed online store.

The default run uses FakeRedis, a dict that mimics the bytes-returning behavior of
redis-py (real Redis returns bytes). This exercises the store's real encoding and
decoding logic. Tests against a live server are gated behind SKEWPROOF_REDIS_URL and
skip unless it is set.
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureDefinition, feature, FeatureRegistry
from skewproof.offline import InMemoryEventSource, OfflineStore, SpineRow
from skewproof.online import OnlineStore
from skewproof.redis_store import OnlineStoreProtocol, RedisOnlineStore


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


class FakeRedis:
    """Mimics the subset of redis-py we use, returning bytes like the real client."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    def set(self, name: str, value: str):
        self.store[name] = value.encode()
        return True

    def get(self, name: str):
        return self.store.get(name)


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


class TestRedisOnlineStore:
    def test_materialize_then_get(self, source, reg) -> None:
        store = RedisOnlineStore(FakeRedis())
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1", "f2"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0
        assert store.get("soil_latest", "f2") == 7.0

    def test_get_unmaterialized_returns_none(self, reg) -> None:
        store = RedisOnlineStore(FakeRedis())
        latest(reg)
        assert store.get("soil_latest", "f1") is None

    def test_materialized_none_returns_none(self, source, reg) -> None:
        store = RedisOnlineStore(FakeRedis())
        fdef = latest(reg)
        store.materialize(fdef, source, ["nobody"], ts(6))
        assert store.get("soil_latest", "nobody") is None

    def test_never_vs_materialized_none_are_distinct_in_storage(self, source, reg) -> None:
        client = FakeRedis()
        store = RedisOnlineStore(client)
        fdef = latest(reg)
        store.materialize(fdef, source, ["nobody"], ts(6))
        # Both read as None, but the materialized-None key exists in storage and the
        # never-materialized one does not.
        assert store.get("soil_latest", "nobody") is None
        assert store.get("soil_latest", "ghost") is None
        assert "skewproof:soil_latest:nobody" in client.store
        assert "skewproof:soil_latest:ghost" not in client.store

    def test_idempotent(self, source, reg) -> None:
        store = RedisOnlineStore(FakeRedis())
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1"], ts(6))
        first = store.get("soil_latest", "f1")
        store.materialize(fdef, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == first

    def test_rematerialize_at_later_as_of_updates(self, source, reg) -> None:
        store = RedisOnlineStore(FakeRedis())
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0
        store.materialize(fdef, source, ["f1"], ts(10))
        assert store.get("soil_latest", "f1") == 99.0

    def test_decodes_string_values_too(self, source, reg) -> None:
        # A client that returns str instead of bytes must still work.
        class StrRedis(FakeRedis):
            def get(self, name: str):
                v = self.store.get(name)
                return v.decode() if v is not None else None

        store = RedisOnlineStore(StrRedis())
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0


class TestSatisfiesProtocol:
    def test_both_stores_satisfy_the_serving_protocol(self) -> None:
        assert isinstance(RedisOnlineStore(FakeRedis()), OnlineStoreProtocol)
        assert isinstance(OnlineStore(), OnlineStoreProtocol)


class TestNoSkewOverRedis:
    """Offline training value equals the value served from Redis."""

    def test_offline_equals_redis(self, source, reg) -> None:
        fdef = latest(reg)
        as_of = ts(6)
        entities = ["f1", "f2"]

        offline = OfflineStore(source)
        training = offline.build_training_set(fdef, [SpineRow(e, as_of) for e in entities])
        offline_vals = {r["entity_id"]: r["soil_latest"] for r in training}

        store = RedisOnlineStore(FakeRedis())
        store.materialize(fdef, source, entities, as_of)
        redis_vals = {e: store.get("soil_latest", e) for e in entities}

        assert offline_vals == redis_vals


# --- live Redis: skipped unless configured --------------------------------------

REDIS_URL = os.environ.get("SKEWPROOF_REDIS_URL")
live = pytest.mark.skipif(REDIS_URL is None, reason="set SKEWPROOF_REDIS_URL to run")


@live
class TestRedisIntegration:
    def test_roundtrip_against_real_redis(self, source, reg) -> None:
        import redis  # imported lazily so the default run needs no server

        client = redis.Redis.from_url(REDIS_URL)
        store = RedisOnlineStore(client)
        fdef = latest(reg)
        store.materialize(fdef, source, ["f1"], ts(6))
        assert store.get("soil_latest", "f1") == 30.0
