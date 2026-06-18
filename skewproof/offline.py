"""
The offline path: building point-in-time correct training sets.

A training set is a list of (entity, label_timestamp) rows. For each row we attach
the feature value as it stood at that label's timestamp, and never later. The
point-in-time filter that enforces this lives in FeatureDefinition.reduce(), so the
offline path here holds no value logic of its own. It fetches an entity's rows and
hands them to reduce() with the right as_of.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .definition import FeatureDefinition


class EventSource(Protocol):
    """An append-only source of (event_ts, value) facts, keyed by entity.

    rows_for returns everything for an entity, unfiltered. The point-in-time filter
    stays in reduce() so it is applied the same way everywhere.
    """

    def rows_for(self, entity_id: str) -> list[tuple[datetime, float]]:
        ...


@dataclass
class InMemoryEventSource:
    """A source backed by a dict, for tests and local runs. A database-backed
    source in a later commit implements the same rows_for contract."""

    data: dict[str, list[tuple[datetime, float]]]

    def rows_for(self, entity_id: str) -> list[tuple[datetime, float]]:
        return list(self.data.get(entity_id, []))


@dataclass
class SpineRow:
    """One training example anchor: an entity observed at an instant."""

    entity_id: str
    as_of: datetime


class OfflineStore:
    """Builds point-in-time correct training sets from an EventSource."""

    def __init__(self, source: EventSource) -> None:
        self._source = source

    def build_training_set(
        self, definition: FeatureDefinition, spine: list[SpineRow]
    ) -> list[dict]:
        """For each spine row, compute the feature value visible at its as_of.

        Because reduce() drops any row with event_ts > as_of, a training set cannot
        contain a value from after its own label. That is leakage prevention by
        construction, not by a separate check.
        """
        out: list[dict] = []
        for row in spine:
            rows = self._source.rows_for(row.entity_id)
            value = definition.reduce(rows, row.as_of)
            out.append(
                {
                    "entity_id": row.entity_id,
                    "as_of": row.as_of,
                    definition.name: value,
                }
            )
        return out
