"""Tests for the materialization job: idempotency, the run report, store-agnosticism."""
from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureDefinition, FeatureRegistry, feature
from skewproof.materialize import MaterializationJob, MaterializationReport
from skewproof.offline import InMemoryEventSource
from skewproof.online import OnlineStore
from skewproof.redis_store import RedisOnlineStore


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


class FakeRedis:
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
            "f1": [(ts(1), 10.0), (ts(5), 30.0), (ts(9), 99.0)],
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


class TestRun:
    def test_writes_values_into_online_store(self, source, reg) -> None:
        online = OnlineStore()
        job = MaterializationJob(online, source)
        fdef = latest(reg)
        job.run(fdef, ["f1", "f2"], ts(6))
        assert online.get("soil_latest", "f1") == 30.0
        assert online.get("soil_latest", "f2") == 7.0

    def test_report_counts(self, source, reg) -> None:
        job = MaterializationJob(OnlineStore(), source)
        fdef = latest(reg)
        report = job.run(fdef, ["f1", "f2"], ts(6))
        assert report == MaterializationReport(
            feature_name="soil_latest",
            as_of=ts(6),
            entities_processed=2,
            values_written=2,
            values_unknown=0,
        )

    def test_report_counts_unknown_values(self, source, reg) -> None:
        # "ghost" has no rows, so its value is unknown at any as_of.
        job = MaterializationJob(OnlineStore(), source)
        fdef = latest(reg)
        report = job.run(fdef, ["f1", "ghost"], ts(6))
        assert report.entities_processed == 2
        assert report.values_written == 1
        assert report.values_unknown == 1

    def test_empty_entity_list(self, source, reg) -> None:
        job = MaterializationJob(OnlineStore(), source)
        report = job.run(latest(reg), [], ts(6))
        assert report.entities_processed == 0
        assert report.values_written == 0
        assert report.values_unknown == 0


class TestIsComplete:
    def test_complete_when_all_known(self, source, reg) -> None:
        report = MaterializationJob(OnlineStore(), source).run(latest(reg), ["f1"], ts(6))
        assert report.is_complete is True

    def test_not_complete_with_unknowns(self, source, reg) -> None:
        report = MaterializationJob(OnlineStore(), source).run(
            latest(reg), ["f1", "ghost"], ts(6)
        )
        assert report.is_complete is False

    def test_not_complete_when_empty(self, source, reg) -> None:
        report = MaterializationJob(OnlineStore(), source).run(latest(reg), [], ts(6))
        assert report.is_complete is False


class TestIdempotency:
    def test_rerun_same_as_of_is_stable(self, source, reg) -> None:
        online = OnlineStore()
        job = MaterializationJob(online, source)
        fdef = latest(reg)
        r1 = job.run(fdef, ["f1", "f2"], ts(6))
        snapshot = {e: online.get("soil_latest", e) for e in ("f1", "f2")}
        r2 = job.run(fdef, ["f1", "f2"], ts(6))
        after = {e: online.get("soil_latest", e) for e in ("f1", "f2")}
        assert snapshot == after
        assert r1 == r2

    def test_rerun_stable_on_redis_backed_bytes(self, source, reg) -> None:
        client = FakeRedis()
        job = MaterializationJob(RedisOnlineStore(client), source)
        fdef = latest(reg)
        job.run(fdef, ["f1"], ts(6))
        first_bytes = dict(client.store)
        job.run(fdef, ["f1"], ts(6))
        assert client.store == first_bytes  # identical bytes after re-run

    def test_later_as_of_updates(self, source, reg) -> None:
        online = OnlineStore()
        job = MaterializationJob(online, source)
        fdef = latest(reg)
        job.run(fdef, ["f1"], ts(6))
        assert online.get("soil_latest", "f1") == 30.0
        job.run(fdef, ["f1"], ts(10))
        assert online.get("soil_latest", "f1") == 99.0


class TestStoreAgnostic:
    def test_runs_over_redis_store(self, source, reg) -> None:
        store = RedisOnlineStore(FakeRedis())
        job = MaterializationJob(store, source)
        fdef = latest(reg)
        report = job.run(fdef, ["f1", "f2"], ts(6))
        assert report.is_complete
        assert store.get("soil_latest", "f1") == 30.0
