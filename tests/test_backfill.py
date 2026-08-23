from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.backfill import BackfillJob, BackfillReport, daily_range
from skewproof.definition import Aggregation, FeatureRegistry, feature
from skewproof.offline import InMemoryEventSource
from skewproof.online import OnlineStore


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


@pytest.fixture
def source() -> InMemoryEventSource:
    return InMemoryEventSource(
        data={
            "f1": [(ts(1), 10.0), (ts(3), 20.0), (ts(5), 30.0)],
            "f2": [(ts(4), 7.0)],
        }
    )


@pytest.fixture
def definition():
    reg = FeatureRegistry()
    return feature(
        reg, name="soil_latest", source="readings", entity_key="farmer_id",
        timestamp_key="event_ts", value_key="moisture", aggregation=Aggregation.LATEST,
    )


class TestBackfillJob:
    def test_runs_one_step_per_as_of(self, source, definition) -> None:
        store = OnlineStore()
        job = BackfillJob(store, source)
        report = job.run(definition, ["f1"], [ts(2), ts(4), ts(6)])
        assert report.as_of_values == (ts(2), ts(4), ts(6))

    def test_store_ends_up_at_the_last_as_of_only(self, source, definition) -> None:
        store = OnlineStore()
        job = BackfillJob(store, source)
        job.run(definition, ["f1"], [ts(2), ts(4), ts(6)])
        # f1's value as of day 2 was 10.0, but only the last step's value (30.0,
        # as of day 6) survives in the store - see the module docstring.
        assert store.get("soil_latest", "f1") == 30.0

    def test_each_step_report_reflects_its_own_as_of(self, source, definition) -> None:
        store = OnlineStore()
        job = BackfillJob(store, source)
        report = job.run(definition, ["f1"], [ts(2), ts(6)])
        assert report.reports[0].as_of == ts(2)
        assert report.reports[1].as_of == ts(6)

    def test_empty_as_of_values_raises(self, source, definition) -> None:
        job = BackfillJob(OnlineStore(), source)
        with pytest.raises(ValueError, match="must not be empty"):
            job.run(definition, ["f1"], [])

    def test_does_not_sort_as_of_values(self, source, definition) -> None:
        store = OnlineStore()
        job = BackfillJob(store, source)
        report = job.run(definition, ["f1"], [ts(6), ts(2)])
        assert report.as_of_values == (ts(6), ts(2))
        # runs in the order given, so the store ends up at day 2's value, not
        # the chronologically-latest one
        assert store.get("soil_latest", "f1") == 10.0


class TestBackfillReport:
    def test_is_complete_true_when_every_step_complete(self, source, definition) -> None:
        job = BackfillJob(OnlineStore(), source)
        report = job.run(definition, ["f1"], [ts(2), ts(6)])
        assert report.is_complete is True

    def test_is_complete_false_when_any_step_incomplete(self, source, definition) -> None:
        job = BackfillJob(OnlineStore(), source)
        report = job.run(definition, ["f1", "ghost"], [ts(2), ts(6)])
        assert report.is_complete is False

    def test_incomplete_steps_filters_to_only_bad_ones(self, source, definition) -> None:
        job = BackfillJob(OnlineStore(), source)
        # f2 has no reading before day 3, so day 2 is incomplete for it; day 6 is not.
        report = job.run(definition, ["f1", "f2"], [ts(2), ts(6)])
        incomplete = report.incomplete_steps()
        assert len(incomplete) == 1
        assert incomplete[0].as_of == ts(2)

    def test_empty_report_is_not_complete(self) -> None:
        assert BackfillReport(()).is_complete is False


class TestDailyRange:
    def test_inclusive_of_both_ends(self) -> None:
        values = daily_range(ts(1), ts(4))
        assert values == [ts(1), ts(2), ts(3), ts(4)]

    def test_single_day_range(self) -> None:
        assert daily_range(ts(5), ts(5)) == [ts(5)]

    def test_preserves_time_of_day(self) -> None:
        values = daily_range(ts(1, hour=6), ts(3, hour=6))
        assert values == [ts(1, 6), ts(2, 6), ts(3, 6)]

    def test_end_before_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end must not be before start"):
            daily_range(ts(5), ts(1))

    def test_feeds_directly_into_backfill_job(self, source, definition) -> None:
        store = OnlineStore()
        job = BackfillJob(store, source)
        report = job.run(definition, ["f1"], daily_range(ts(2), ts(6)))
        assert len(report.reports) == 5
        assert store.get("soil_latest", "f1") == 30.0
