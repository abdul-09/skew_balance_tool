"""
The online path: serving feature values with a fast key lookup.

Materialization computes each entity's value at an instant and writes it to a
key-value store. Serving reads it back. The value is computed by the same
FeatureDefinition.reduce() the offline path uses, so for a given (entity, as_of)
the online value and the offline training value are the same number. That equality
is the whole point of the project, and commit 3's test proves it.
"""
from __future__ import annotations

from datetime import datetime

from .definition import FeatureDefinition
from .offline import EventSource


class OnlineStore:
    """A key-value serving store. This commit uses an in-process dict; a later
    commit swaps in Redis behind the same get/materialize contract."""

    def __init__(self) -> None:
        self._kv: dict[str, float | None] = {}

    @staticmethod
    def _key(feature_name: str, entity_id: str) -> str:
        return f"{feature_name}:{entity_id}"

    def materialize(
        self,
        definition: FeatureDefinition,
        source: EventSource,
        entity_ids: list[str],
        as_of: datetime,
    ) -> None:
        """Compute each entity's value at as_of and write it to the store.

        Uses the same reduce() as the offline path. Re-running with the same inputs
        overwrites with the same value, so the operation is safe to repeat.
        """
        for entity_id in entity_ids:
            rows = source.rows_for(entity_id)
            self._kv[self._key(definition.name, entity_id)] = definition.reduce(
                rows, as_of
            )

    def get(self, feature_name: str, entity_id: str) -> float | None:
        """Return the materialized value, or None if it was never materialized."""
        return self._kv.get(self._key(feature_name, entity_id))
