"""
Tests for the CSV-backed EventSource.

Writes a real CSV file per test (via pytest's tmp_path) and reads it back through
CsvEventSource, so this exercises actual file I/O and csv parsing, not a mock.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

import pytest

from skewproof.csv_source import CsvEventSource
from skewproof.definition import Aggregation, FeatureDefinition
from skewproof.offline import OfflineStore, SpineRow


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


def write_csv(path: Path, rows: list[dict]) -> Path:
    file_path = path / "readings.csv"
    with open(file_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["farmer_id", "event_ts", "moisture"])
        writer.writeheader()
        writer.writerows(rows)
    return file_path


@pytest.fixture
def csv_path(tmp_path: Path) -> Path:
    return write_csv(
        tmp_path,
        [
            {"farmer_id": "f1", "event_ts": ts(1).isoformat(), "moisture": "10.0"},
            {"farmer_id": "f1", "event_ts": ts(5).isoformat(), "moisture": "30.0"},
            {"farmer_id": "f1", "event_ts": ts(9).isoformat(), "moisture": "99.0"},
            {"farmer_id": "f2", "event_ts": ts(2).isoformat(), "moisture": "5.0"},
        ],
    )


def make_source(path: Path) -> CsvEventSource:
    return CsvEventSource(
        path=path,
        entity_column="farmer_id",
        timestamp_column="event_ts",
        value_column="moisture",
    )


def latest() -> FeatureDefinition:
    return FeatureDefinition(
        name="soil_latest",
        source="readings",
        entity_key="farmer_id",
        timestamp_key="event_ts",
        value_key="moisture",
        aggregation=Aggregation.LATEST,
    )


class TestRowsFor:
    def test_returns_only_the_requested_entity(self, csv_path: Path) -> None:
        rows = make_source(csv_path).rows_for("f1")
        assert rows == [(ts(1), 10.0), (ts(5), 30.0), (ts(9), 99.0)]

    def test_different_entity_is_isolated(self, csv_path: Path) -> None:
        rows = make_source(csv_path).rows_for("f2")
        assert rows == [(ts(2), 5.0)]

    def test_unknown_entity_returns_empty(self, csv_path: Path) -> None:
        assert make_source(csv_path).rows_for("ghost") == []

    def test_accepts_str_path_as_well_as_path_object(self, csv_path: Path) -> None:
        rows = CsvEventSource(
            path=str(csv_path),
            entity_column="farmer_id",
            timestamp_column="event_ts",
            value_column="moisture",
        ).rows_for("f1")
        assert len(rows) == 3


class TestValidation:
    def test_missing_entity_column_raises_at_construction(self) -> None:
        with pytest.raises(ValueError, match="entity_column is required"):
            CsvEventSource(
                path="unused.csv", entity_column="", timestamp_column="t", value_column="v"
            )

    def test_missing_timestamp_column_raises_at_construction(self) -> None:
        with pytest.raises(ValueError, match="timestamp_column is required"):
            CsvEventSource(
                path="unused.csv", entity_column="e", timestamp_column="", value_column="v"
            )

    def test_missing_value_column_raises_at_construction(self) -> None:
        with pytest.raises(ValueError, match="value_column is required"):
            CsvEventSource(
                path="unused.csv", entity_column="e", timestamp_column="t", value_column=""
            )

    def test_unknown_column_in_header_raises_at_read_time(self, tmp_path: Path) -> None:
        path = write_csv(
            tmp_path, [{"farmer_id": "f1", "event_ts": ts(1).isoformat(), "moisture": "1.0"}]
        )
        src = CsvEventSource(
            path=path,
            entity_column="farmer_id",
            timestamp_column="event_ts",
            value_column="not_a_real_column",
        )
        with pytest.raises(ValueError, match="missing column"):
            src.rows_for("f1")

    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        src = make_source(tmp_path / "does_not_exist.csv")
        with pytest.raises(FileNotFoundError):
            src.rows_for("f1")

    def test_malformed_value_raises_value_error(self, tmp_path: Path) -> None:
        path = write_csv(
            tmp_path,
            [{"farmer_id": "f1", "event_ts": ts(1).isoformat(), "moisture": "not_a_number"}],
        )
        with pytest.raises(ValueError):
            make_source(path).rows_for("f1")

    def test_malformed_timestamp_raises_value_error(self, tmp_path: Path) -> None:
        path = write_csv(
            tmp_path, [{"farmer_id": "f1", "event_ts": "not_a_timestamp", "moisture": "1.0"}]
        )
        with pytest.raises(ValueError):
            make_source(path).rows_for("f1")


class TestIntegrationWithOfflineStore:
    def test_builds_point_in_time_training_set(self, csv_path: Path) -> None:
        store = OfflineStore(make_source(csv_path))
        [row] = store.build_training_set(latest(), [SpineRow("f1", ts(6))])
        assert row["soil_latest"] == 30.0  # not 99.0: that reading is after as_of
