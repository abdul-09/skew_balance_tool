"""
A SQLite-backed online store.

Same contract as the in-process OnlineStore and RedisOnlineStore: materialize()
computes each entity's value at an instant and writes it; get() reads it back.
Serving code depends on OnlineStoreProtocol, so it works against this store
without change, same as the other two.

This is the middle ground between them: values survive a process restart (unlike
the in-process dict), but there's no server to run (unlike Redis) - just a file,
or ":memory:" for tests. Good for a single-process deployment or local
development where durability matters but standing up Redis doesn't.

Values are written through the same FeatureDefinition.reduce() as every other
path, so a value served from here equals the training value for the same
(entity, as_of). SQLite stores NULL natively, so an unknown feature value (None)
and a never-materialized key are both represented directly rather than needing
the sentinel-string trick RedisOnlineStore uses for its string-only store.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from types import TracebackType

from .definition import FeatureDefinition
from .offline import EventSource

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS skewproof_features (
    feature_name TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    value        REAL,
    PRIMARY KEY (feature_name, entity_id)
)
"""

_UPSERT = """
INSERT INTO skewproof_features (feature_name, entity_id, value)
VALUES (?, ?, ?)
ON CONFLICT (feature_name, entity_id) DO UPDATE SET value = excluded.value
"""

_SELECT = """
SELECT value FROM skewproof_features WHERE feature_name = ? AND entity_id = ?
"""


class SqliteOnlineStore:
    """Serves features out of SQLite. Construct with a file path or ":memory:"."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path)
        self._conn.execute(_CREATE_TABLE)
        self._conn.commit()

    def materialize(
        self,
        definition: FeatureDefinition,
        source: EventSource,
        entity_ids: list[str],
        as_of: datetime,
    ) -> None:
        """Compute each entity's value at as_of and upsert it into the table.

        Uses the same reduce() as the offline path. Re-running with the same
        inputs overwrites with the same value, so the operation is safe to repeat.
        """
        for entity_id in entity_ids:
            rows = source.rows_for(entity_id)
            value = definition.reduce(rows, as_of)
            self._conn.execute(_UPSERT, (definition.name, entity_id, value))
        self._conn.commit()

    def get(self, feature_name: str, entity_id: str) -> float | None:
        """Return the materialized value, or None if it was never materialized
        (no row) or if it was materialized with an unknown value (row with a
        NULL value column) - both cases naturally return None here."""
        cur = self._conn.execute(_SELECT, (feature_name, entity_id))
        row = cur.fetchone()
        return None if row is None else row[0]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SqliteOnlineStore:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
