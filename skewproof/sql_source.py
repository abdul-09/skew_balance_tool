"""
A SQL-backed EventSource.

This pulls an entity's (event_ts, value) rows out of a relational table so the
offline path can build training sets from a real database instead of a dict. The
same class works against SQLite (used in this commit's tests) and Postgres (used in
deployment) because the query is plain parameterized SQL.

The point-in-time filter still lives in FeatureDefinition.reduce(), not here.
rows_for returns the full per-entity history; reduce() decides what is visible at a
given as_of. Keeping the source "dumb" is deliberate: one place owns the time logic.

There is one optional pushdown. Pulling all of history for a very active entity is
wasteful, so rows_for accepts an optional upper bound (max_ts) that filters in SQL.
It is only ever set to the as_of the caller already intends to reduce at, so it can
never hide a row that reduce() would have kept. The equivalence is covered by a test.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


class DbApiConnection(Protocol):
    """The slice of PEP 249 we use. psycopg2 and sqlite3 both satisfy it."""

    def cursor(self) -> Any:
        ...


@dataclass
class SqlEventSource:
    """Reads events for one entity from a table.

    table:          source table name
    entity_column:  column identifying the entity
    timestamp_column: event-time column
    value_column:   numeric value column
    paramstyle:     "qmark" for sqlite (?), "format" for psycopg2 (%s)
    """

    connection: DbApiConnection
    table: str
    entity_column: str
    timestamp_column: str
    value_column: str
    paramstyle: str = "qmark"

    def _placeholder(self) -> str:
        if self.paramstyle == "qmark":
            return "?"
        if self.paramstyle == "format":
            return "%s"
        raise ValueError(f"unsupported paramstyle {self.paramstyle!r}")

    def rows_for(
        self, entity_id: str, max_ts: datetime | None = None
    ) -> list[tuple[datetime, float]]:
        ph = self._placeholder()
        sql = (
            f"SELECT {self.timestamp_column}, {self.value_column} "
            f"FROM {self.table} "
            f"WHERE {self.entity_column} = {ph}"
        )
        params: list[object] = [entity_id]
        if max_ts is not None:
            sql += f" AND {self.timestamp_column} <= {ph}"
            params.append(max_ts)
        sql += f" ORDER BY {self.timestamp_column} ASC"

        cur = self.connection.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        return [(_as_datetime(ts), float(val)) for (ts, val) in rows]


def _as_datetime(value: object) -> datetime:
    """SQLite hands back ISO strings for timestamps; psycopg2 hands back datetimes.
    Normalize both to datetime so reduce() sees a consistent type."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"cannot interpret {value!r} as a datetime")
