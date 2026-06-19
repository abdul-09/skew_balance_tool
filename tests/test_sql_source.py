"""
Tests for the SQL-backed EventSource.

Most run against a real SQLite database created in-process: this exercises the
actual query, parameter binding, ordering, and timestamp normalization, not a mock.
The query is plain SQL, so passing here is strong evidence it works on Postgres too.

The Postgres-specific tests are gated behind SKEWPROOF_PG_DSN. They are skipped
unless that environment variable points at a running database, so the default test
run stays fast and needs no services.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime

import pytest

from skewproof.definition import Aggregation, FeatureDefinition
from skewproof.offline import OfflineStore, SpineRow
from skewproof.sql_source import SqlEventSource, _as_datetime


def ts(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 1, day, hour)


@pytest.fixture
def sqlite_conn() -> sqlite3.Connection:
    # Python 3.12 deprecated the implicit datetime->SQLite adapter. Register an
    # explicit one so the test binds datetimes cleanly. This is a SQLite-only
    # concern; Postgres handles TIMESTAMPTZ natively, so production code is unaffected.
    sqlite3.register_adapter(datetime, lambda d: d.isoformat())
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE soil_readings (farmer_id TEXT, event_ts TEXT, moisture REAL)"
    )
    rows = [
        ("f1", ts(1).isoformat(), 10.0),
        ("f1", ts(3).isoformat(), 20.0),
        ("f1", ts(5).isoformat(), 30.0),
        ("f1", ts(9).isoformat(), 99.0),
        ("f2", ts(2).isoformat(), 5.0),
        ("f2", ts(4).isoformat(), 7.0),
    ]
    conn.executemany("INSERT INTO soil_readings VALUES (?, ?, ?)", rows)
    conn.commit()
    return conn


def make_source(conn: sqlite3.Connection) -> SqlEventSource:
    return SqlEventSource(
        connection=conn,
        table="soil_readings",
        entity_column="farmer_id",
        timestamp_column="event_ts",
        value_column="moisture",
        paramstyle="qmark",
    )


def latest() -> FeatureDefinition:
    return FeatureDefinition(
        name="soil_latest",
        source="soil_readings",
        entity_key="farmer_id",
        timestamp_key="event_ts",
        value_key="moisture",
        aggregation=Aggregation.LATEST,
    )


class TestRowsFor:
    def test_returns_ordered_rows(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        rows = src.rows_for("f1")
        assert rows == [(ts(1), 10.0), (ts(3), 20.0), (ts(5), 30.0), (ts(9), 99.0)]

    def test_unknown_entity_is_empty(self, sqlite_conn) -> None:
        assert make_source(sqlite_conn).rows_for("nobody") == []

    def test_values_are_floats(self, sqlite_conn) -> None:
        rows = make_source(sqlite_conn).rows_for("f2")
        assert all(isinstance(v, float) for _, v in rows)

    def test_max_ts_pushdown_filters_in_sql(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        rows = src.rows_for("f1", max_ts=ts(6))
        assert rows == [(ts(1), 10.0), (ts(3), 20.0), (ts(5), 30.0)]  # no day 9


class TestPushdownEquivalence:
    """max_ts is only ever set to the as_of we reduce at, so it must not change the
    reduced result versus pulling full history."""

    def test_reduce_same_with_and_without_pushdown(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        fdef = latest()
        as_of = ts(6)
        full = fdef.reduce(src.rows_for("f1"), as_of)
        pushed = fdef.reduce(src.rows_for("f1", max_ts=as_of), as_of)
        assert full == pushed == 30.0


class TestOfflineOverSql:
    """The offline store works over the SQL source with no code change."""

    def test_training_set_from_sqlite(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        store = OfflineStore(src)
        fdef = latest()
        rows = store.build_training_set(fdef, [SpineRow("f1", ts(6)), SpineRow("f2", ts(6))])
        by_entity = {r["entity_id"]: r["soil_latest"] for r in rows}
        assert by_entity == {"f1": 30.0, "f2": 7.0}

    def test_leakage_still_prevented_over_sql(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        store = OfflineStore(src)
        fdef = latest()
        [row] = store.build_training_set(fdef, [SpineRow("f1", ts(6))])
        assert row["soil_latest"] == 30.0  # not 99.0


class TestParamStyle:
    def test_format_paramstyle_for_postgres(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        src.paramstyle = "format"
        assert src._placeholder() == "%s"

    def test_qmark_paramstyle_for_sqlite(self, sqlite_conn) -> None:
        assert make_source(sqlite_conn)._placeholder() == "?"

    def test_unsupported_paramstyle_raises(self, sqlite_conn) -> None:
        src = make_source(sqlite_conn)
        src.paramstyle = "named"
        with pytest.raises(ValueError, match="unsupported paramstyle"):
            src._placeholder()


class TestAsDatetime:
    def test_passthrough_datetime(self) -> None:
        d = ts(3)
        assert _as_datetime(d) is d

    def test_parse_iso_string(self) -> None:
        assert _as_datetime("2026-01-03T00:00:00") == ts(3)

    def test_bad_type_raises(self) -> None:
        with pytest.raises(TypeError, match="cannot interpret"):
            _as_datetime(12345)


# --- Postgres integration: skipped unless a live DB is configured ----------------

PG_DSN = os.environ.get("SKEWPROOF_PG_DSN")
pg = pytest.mark.skipif(PG_DSN is None, reason="set SKEWPROOF_PG_DSN to run Postgres tests")


@pg
class TestPostgresIntegration:
    @pytest.fixture
    def pg_conn(self):
        import psycopg2  # imported lazily so the default run needs no driver

        conn = psycopg2.connect(PG_DSN)
        cur = conn.cursor()
        cur.execute("DROP TABLE IF EXISTS soil_readings")
        cur.execute(
            "CREATE TABLE soil_readings ("
            "farmer_id TEXT, event_ts TIMESTAMPTZ, moisture DOUBLE PRECISION)"
        )
        for e, t, v in [
            ("f1", ts(1), 10.0),
            ("f1", ts(3), 20.0),
            ("f1", ts(5), 30.0),
            ("f1", ts(9), 99.0),
        ]:
            cur.execute("INSERT INTO soil_readings VALUES (%s, %s, %s)", (e, t, v))
        conn.commit()
        yield conn
        conn.close()

    def test_point_in_time_on_postgres(self, pg_conn) -> None:
        src = SqlEventSource(
            connection=pg_conn,
            table="soil_readings",
            entity_column="farmer_id",
            timestamp_column="event_ts",
            value_column="moisture",
            paramstyle="format",
        )
        store = OfflineStore(src)
        fdef = latest()
        [row] = store.build_training_set(fdef, [SpineRow("f1", ts(6))])
        assert row["soil_latest"] == 30.0
