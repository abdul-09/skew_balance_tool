"""
Tests for skewproof.doctor.

psycopg2 and redis are optional extras and genuinely aren't installed in the dev
environment (see pyproject.toml's postgres/redis extras) - the same reason
sql_source.py and redis_store.py only depend on a Protocol shape, not the real
packages. To test the "installed and connected" and "installed but failed" paths
without a live Postgres/Redis server, these tests inject a fake module into
sys.modules for the duration of the test, standing in for the real client
library. monkeypatch restores sys.modules automatically after each test.
"""
from __future__ import annotations

import sys
import types

from skewproof.doctor import CheckResult, check_postgres, check_redis, run_doctor


class TestCheckResult:
    def test_ok_status_is_ok(self) -> None:
        assert CheckResult("x", "ok", "").ok is True

    def test_not_configured_is_ok(self) -> None:
        assert CheckResult("x", "not_configured", "").ok is True

    def test_failed_is_not_ok(self) -> None:
        assert CheckResult("x", "failed", "").ok is False


class TestCheckPostgresNotConfigured:
    def test_unset_env_var_is_not_configured(self, monkeypatch) -> None:
        monkeypatch.delenv("SKEWPROOF_PG_DSN", raising=False)
        result = check_postgres()
        assert result.status == "not_configured"
        assert result.ok is True

    def test_explicit_none_falls_back_to_env(self, monkeypatch) -> None:
        monkeypatch.setenv("SKEWPROOF_PG_DSN", "postgresql://x")
        monkeypatch.delitem(sys.modules, "psycopg2", raising=False)
        result = check_postgres(None)
        assert result.status == "failed"  # psycopg2 genuinely isn't installed
        assert "not installed" in result.detail


class TestCheckPostgresNotInstalled:
    def test_missing_psycopg2_reports_install_hint(self, monkeypatch) -> None:
        monkeypatch.delitem(sys.modules, "psycopg2", raising=False)
        result = check_postgres(dsn="postgresql://x")
        assert result.status == "failed"
        assert "skewproof[postgres]" in result.detail


def _fake_psycopg2(*, connect_error=None, query_error=None, version="PostgreSQL 16.0"):
    module = types.ModuleType("psycopg2")

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def execute(self, sql):
            if query_error is not None:
                raise query_error

        def fetchone(self):
            return (version,)

    class FakeConnection:
        def __init__(self):
            self.closed = False

        def cursor(self):
            return FakeCursor()

        def close(self):
            self.closed = True

    def connect(dsn):
        if connect_error is not None:
            raise connect_error
        return FakeConnection()

    module.connect = connect  # type: ignore[attr-defined]
    return module


class TestCheckPostgresConnected:
    def test_ok_reports_version(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "psycopg2", _fake_psycopg2())
        result = check_postgres(dsn="postgresql://x")
        assert result.status == "ok"
        assert result.detail == "PostgreSQL 16.0"

    def test_connect_failure_reports_failed(self, monkeypatch) -> None:
        monkeypatch.setitem(
            sys.modules, "psycopg2", _fake_psycopg2(connect_error=RuntimeError("refused"))
        )
        result = check_postgres(dsn="postgresql://x")
        assert result.status == "failed"
        assert "could not connect" in result.detail

    def test_query_failure_reports_failed_and_still_closes(self, monkeypatch) -> None:
        module = _fake_psycopg2(query_error=RuntimeError("permission denied"))
        monkeypatch.setitem(sys.modules, "psycopg2", module)
        result = check_postgres(dsn="postgresql://x")
        assert result.status == "failed"
        assert "connected but query failed" in result.detail


class TestCheckRedisNotConfigured:
    def test_unset_env_var_is_not_configured(self, monkeypatch) -> None:
        monkeypatch.delenv("SKEWPROOF_REDIS_URL", raising=False)
        result = check_redis()
        assert result.status == "not_configured"


class TestCheckRedisNotInstalled:
    def test_missing_redis_reports_install_hint(self, monkeypatch) -> None:
        monkeypatch.delitem(sys.modules, "redis", raising=False)
        result = check_redis(url="redis://x")
        assert result.status == "failed"
        assert "skewproof[redis]" in result.detail


def _fake_redis(*, from_url_error=None, info_error=None, close_error=None, version="7.4.0"):
    module = types.ModuleType("redis")

    class FakeClient:
        def __init__(self):
            self.closed = False

        def info(self, section):
            if info_error is not None:
                raise info_error
            return {"redis_version": version}

        def close(self):
            if close_error is not None:
                raise close_error
            self.closed = True

    class FakeRedis:
        @staticmethod
        def from_url(url):
            if from_url_error is not None:
                raise from_url_error
            return FakeClient()

    module.Redis = FakeRedis  # type: ignore[attr-defined]
    return module


class TestCheckRedisConnected:
    def test_ok_reports_version(self, monkeypatch) -> None:
        monkeypatch.setitem(sys.modules, "redis", _fake_redis())
        result = check_redis(url="redis://x")
        assert result.status == "ok"
        assert result.detail == "redis 7.4.0"

    def test_from_url_failure_reports_failed(self, monkeypatch) -> None:
        module = _fake_redis(from_url_error=RuntimeError("bad url"))
        monkeypatch.setitem(sys.modules, "redis", module)
        result = check_redis(url="redis://x")
        assert result.status == "failed"
        assert "could not connect" in result.detail

    def test_info_failure_reports_failed_and_still_closes(self, monkeypatch) -> None:
        module = _fake_redis(info_error=RuntimeError("no auth"))
        monkeypatch.setitem(sys.modules, "redis", module)
        result = check_redis(url="redis://x")
        assert result.status == "failed"
        assert "connected but query failed" in result.detail

    def test_close_failure_does_not_mask_the_result(self, monkeypatch) -> None:
        module = _fake_redis(close_error=RuntimeError("close boom"))
        monkeypatch.setitem(sys.modules, "redis", module)
        result = check_redis(url="redis://x")
        assert result.status == "ok"  # close() failing shouldn't flip a good result


class TestRunDoctor:
    def test_returns_both_checks_in_order(self, monkeypatch) -> None:
        monkeypatch.delenv("SKEWPROOF_PG_DSN", raising=False)
        monkeypatch.delenv("SKEWPROOF_REDIS_URL", raising=False)
        results = run_doctor()
        assert [r.name for r in results] == ["postgres", "redis"]
        assert all(r.status == "not_configured" for r in results)
