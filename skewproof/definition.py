"""
A feature defined once.

A feature is a pure function of (entity_id, as_of). The same definition object
drives both the training path and the serving path that come in later commits, so
the two cannot disagree. There is no second copy of the value logic to drift.

This module is pure: no storage, no network, no datetime.now(). Time is always
passed in as as_of, which keeps the point-in-time logic honest and the tests
deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Iterable


class Aggregation(str, Enum):
    """How to collapse the rows visible at as_of into one value."""

    LATEST = "latest"  # most recent value at or before as_of
    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"
    MAX = "max"
    MIN = "min"


@dataclass(frozen=True)
class FeatureDefinition:
    """
    A feature, declared once. Frozen because a definition is a value: it should not
    change underneath a training run or a serving call.

    name:           unique feature name
    source:         the append-only source the feature reads from
    entity_key:     column identifying the entity, e.g. "farmer_id"
    timestamp_key:  event-time column (when the fact became true)
    value_key:      column holding the raw value
    aggregation:    how to collapse visible rows into the value
    window_seconds: optional lookback ending at as_of; None means all history
    """

    name: str
    source: str
    entity_key: str
    timestamp_key: str
    value_key: str
    aggregation: Aggregation = Aggregation.LATEST
    window_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("feature name is required")
        if not self.source:
            raise ValueError("source is required")
        if self.window_seconds is not None and self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive or None")

    def reduce(
        self, rows: Iterable[tuple[datetime, float]], as_of: datetime
    ) -> float | None:
        """
        Turn one entity's rows into its value at as_of.

        rows are (event_ts, value) pairs, unfiltered. The point-in-time filter
        (event_ts <= as_of) and the optional window are applied here, in one place,
        so every caller gets the same answer. Returns None when nothing is visible.
        """
        visible = [(ts, v) for (ts, v) in rows if ts <= as_of]
        if self.window_seconds is not None:
            lo = as_of.timestamp() - self.window_seconds
            visible = [(ts, v) for (ts, v) in visible if ts.timestamp() >= lo]
        if not visible:
            return None

        visible.sort(key=lambda r: r[0])
        values = [v for (_, v) in visible]

        agg = self.aggregation
        if agg is Aggregation.LATEST:
            return float(visible[-1][1])
        if agg is Aggregation.SUM:
            return float(sum(values))
        if agg is Aggregation.MEAN:
            return float(sum(values) / len(values))
        if agg is Aggregation.COUNT:
            return float(len(values))
        if agg is Aggregation.MAX:
            return float(max(values))
        return float(min(values))  # only MIN is left; the enum is closed


@dataclass
class FeatureRegistry:
    """Maps a name to exactly one definition. No shadow copies of a feature."""

    _defs: dict[str, FeatureDefinition] = field(default_factory=dict)

    def register(self, definition: FeatureDefinition) -> FeatureDefinition:
        if definition.name in self._defs:
            raise ValueError(f"feature {definition.name!r} already registered")
        self._defs[definition.name] = definition
        return definition

    def get(self, name: str) -> FeatureDefinition:
        if name not in self._defs:
            raise KeyError(f"feature {name!r} is not registered")
        return self._defs[name]

    def all(self) -> list[FeatureDefinition]:
        return list(self._defs.values())


def feature(registry: FeatureRegistry, **kwargs) -> FeatureDefinition:
    """Build a FeatureDefinition and register it in one call."""
    return registry.register(FeatureDefinition(**kwargs))
