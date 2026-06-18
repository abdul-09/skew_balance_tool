"""Tests for the core primitive: value semantics in isolation, no I/O."""
from __future__ import annotations

from datetime import datetime

import pytest

from skewproof.definition import (
    Aggregation,
    FeatureDefinition,
    FeatureRegistry,
    feature,
)


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


def make(agg: Aggregation, window: int | None = None) -> FeatureDefinition:
    return FeatureDefinition(
        name=f"f_{agg.value}_{window}",
        source="readings",
        entity_key="entity_id",
        timestamp_key="event_ts",
        value_key="value",
        aggregation=agg,
        window_seconds=window,
    )


ROWS = [
    (ts(1), 10.0),
    (ts(3), 20.0),
    (ts(5), 30.0),
    (ts(9), 99.0),  # future relative to as_of = day 6
]


class TestPointInTime:
    def test_latest_excludes_future(self) -> None:
        assert make(Aggregation.LATEST).reduce(ROWS, ts(6)) == 30.0

    def test_latest_includes_once_in_past(self) -> None:
        assert make(Aggregation.LATEST).reduce(ROWS, ts(10)) == 99.0

    def test_boundary_is_inclusive(self) -> None:
        assert make(Aggregation.LATEST).reduce(ROWS, ts(5)) == 30.0

    def test_value_at_first_event(self) -> None:
        assert make(Aggregation.LATEST).reduce(ROWS, ts(1)) == 10.0

    def test_none_before_any_event(self) -> None:
        assert make(Aggregation.LATEST).reduce(ROWS, datetime(2025, 12, 31)) is None

    def test_empty_rows_returns_none(self) -> None:
        assert make(Aggregation.LATEST).reduce([], ts(6)) is None


class TestAggregations:
    def test_sum(self) -> None:
        assert make(Aggregation.SUM).reduce(ROWS, ts(6)) == 60.0

    def test_mean(self) -> None:
        assert make(Aggregation.MEAN).reduce(ROWS, ts(6)) == 20.0

    def test_count(self) -> None:
        assert make(Aggregation.COUNT).reduce(ROWS, ts(6)) == 3.0

    def test_max(self) -> None:
        assert make(Aggregation.MAX).reduce(ROWS, ts(6)) == 30.0

    def test_min(self) -> None:
        assert make(Aggregation.MIN).reduce(ROWS, ts(6)) == 10.0


class TestWindow:
    def test_window_includes_lower_bound(self) -> None:
        d = make(Aggregation.SUM, window=3 * 24 * 3600)
        assert d.reduce(ROWS, ts(6)) == 50.0

    def test_window_excludes_older(self) -> None:
        d = make(Aggregation.SUM, window=1 * 24 * 3600)
        assert d.reduce(ROWS, ts(6)) == 30.0

    def test_window_none_means_all_history(self) -> None:
        assert make(Aggregation.COUNT, window=None).reduce(ROWS, ts(6)) == 3.0


class TestValidation:
    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValueError, match="name is required"):
            FeatureDefinition(name="", source="s", entity_key="e", timestamp_key="t", value_key="v")

    def test_empty_source_rejected(self) -> None:
        with pytest.raises(ValueError, match="source is required"):
            FeatureDefinition(name="n", source="", entity_key="e", timestamp_key="t", value_key="v")

    def test_nonpositive_window_rejected(self) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            FeatureDefinition(
                name="n", source="s", entity_key="e", timestamp_key="t", value_key="v",
                window_seconds=0,
            )

    def test_default_aggregation_is_latest(self) -> None:
        d = FeatureDefinition(name="n", source="s", entity_key="e", timestamp_key="t", value_key="v")
        assert d.aggregation is Aggregation.LATEST


class TestRegistry:
    def test_register_and_get(self) -> None:
        reg = FeatureRegistry()
        d = feature(reg, name="x", source="s", entity_key="e", timestamp_key="t", value_key="v")
        assert reg.get("x") is d

    def test_duplicate_rejected(self) -> None:
        reg = FeatureRegistry()
        kw = dict(name="x", source="s", entity_key="e", timestamp_key="t", value_key="v")
        feature(reg, **kw)
        with pytest.raises(ValueError, match="already registered"):
            feature(reg, **kw)

    def test_get_unknown_raises(self) -> None:
        reg = FeatureRegistry()
        with pytest.raises(KeyError, match="not registered"):
            reg.get("nope")

    def test_all_lists_definitions(self) -> None:
        reg = FeatureRegistry()
        feature(reg, name="a", source="s", entity_key="e", timestamp_key="t", value_key="v")
        feature(reg, name="b", source="s", entity_key="e", timestamp_key="t", value_key="v")
        assert sorted(d.name for d in reg.all()) == ["a", "b"]
