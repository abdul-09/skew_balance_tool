from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.batch import BatchMaterializationJob, BatchMaterializationReport
from skewproof.definition import Aggregation, FeatureRegistry, feature
from skewproof.offline import InMemoryEventSource
from skewproof.online import OnlineStore


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


@pytest.fixture
def moisture_source() -> InMemoryEventSource:
    return InMemoryEventSource(
        data={"f1": [(ts(1), 10.0), (ts(5), 30.0)], "f2": [(ts(2), 5.0)]}
    )


@pytest.fixture
def rainfall_source() -> InMemoryEventSource:
    return InMemoryEventSource(data={"f1": [(ts(3), 1.0)], "f2": [(ts(4), 2.0)]})


@pytest.fixture
def reg(moisture_source, rainfall_source) -> FeatureRegistry:
    r = FeatureRegistry()
    feature(
        r, name="soil_moisture", source="moisture", entity_key="farmer_id",
        timestamp_key="event_ts", value_key="moisture", aggregation=Aggregation.LATEST,
    )
    feature(
        r, name="rainfall", source="rainfall", entity_key="farmer_id",
        timestamp_key="event_ts", value_key="mm", aggregation=Aggregation.LATEST,
    )
    return r


class TestBatchRun:
    def test_runs_every_feature_in_the_registry_by_default(
        self, reg, moisture_source, rainfall_source
    ) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        report = batch.run(
            reg,
            sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
            entity_ids=["f1", "f2"],
            as_of=ts(6),
        )
        assert report.feature_names == ("soil_moisture", "rainfall")
        assert store.get("soil_moisture", "f1") == 30.0
        assert store.get("rainfall", "f1") == 1.0

    def test_runs_only_the_requested_subset(self, reg, moisture_source, rainfall_source) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        report = batch.run(
            reg,
            sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
            entity_ids=["f1"],
            as_of=ts(6),
            feature_names=["soil_moisture"],
        )
        assert report.feature_names == ("soil_moisture",)
        assert store.get("rainfall", "f1") is None  # never materialized

    def test_is_complete_true_when_every_feature_complete(
        self, reg, moisture_source, rainfall_source
    ) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        report = batch.run(
            reg,
            sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
            entity_ids=["f1", "f2"],
            as_of=ts(6),
        )
        assert report.is_complete is True

    def test_is_complete_false_when_any_feature_incomplete(
        self, reg, moisture_source, rainfall_source
    ) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        report = batch.run(
            reg,
            sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
            entity_ids=["f1", "ghost"],
            as_of=ts(6),
        )
        assert report.is_complete is False

    def test_per_feature_entity_ids(self, reg, moisture_source, rainfall_source) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        report = batch.run(
            reg,
            sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
            entity_ids={"soil_moisture": ["f1"], "rainfall": ["f2"]},
            as_of=ts(6),
        )
        assert report.is_complete is True
        assert store.get("soil_moisture", "f1") == 30.0
        assert store.get("soil_moisture", "f2") is None
        assert store.get("rainfall", "f2") == 2.0

    def test_missing_source_raises_before_writing_anything(
        self, reg, moisture_source, rainfall_source
    ) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        with pytest.raises(ValueError, match="no source given for feature"):
            batch.run(
                reg,
                sources={"soil_moisture": moisture_source},  # missing "rainfall"
                entity_ids=["f1"],
                as_of=ts(6),
            )
        assert store.get("soil_moisture", "f1") is None  # nothing written

    def test_missing_per_feature_entity_ids_raises(
        self, reg, moisture_source, rainfall_source
    ) -> None:
        store = OnlineStore()
        batch = BatchMaterializationJob(store)
        with pytest.raises(ValueError, match="no entity_ids given for feature"):
            batch.run(
                reg,
                sources={"soil_moisture": moisture_source, "rainfall": rainfall_source},
                entity_ids={"soil_moisture": ["f1"]},  # missing "rainfall"
                as_of=ts(6),
            )


class TestBatchMaterializationReport:
    def test_empty_report_is_not_complete(self) -> None:
        assert BatchMaterializationReport(()).is_complete is False
