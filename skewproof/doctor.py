"""
Environment/connectivity checks for the optional Postgres and Redis backends.

Reads the same two env vars the integration tests key off of - SKEWPROOF_PG_DSN
and SKEWPROOF_REDIS_URL, see tests/test_sql_source.py and tests/test_redis_store.py
- so "does my local setup actually work" and "will those tests run" are the same
question, checked the same way.

A check that's unconfigured (its env var unset) is a distinct outcome from one
that's configured and failing to connect: an unconfigured backend is the normal
state for a dev machine that only uses the in-memory/SQLite/CSV backends, and
should not fail a script built on top of this. Only "failed" should.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Status = Literal["ok", "not_configured", "failed"]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: Status
    detail: str

    @property
    def ok(self) -> bool:
        """True unless the check ran and failed. Not-configured counts as ok:
        it isn't an error for a backend to simply not be set up."""
        return self.status != "failed"


def check_postgres(dsn: str | None = None) -> CheckResult:
    dsn = dsn if dsn is not None else os.environ.get("SKEWPROOF_PG_DSN")
    if not dsn:
        return CheckResult("postgres", "not_configured", "SKEWPROOF_PG_DSN is not set")

    try:
        import psycopg2
    except ImportError:
        return CheckResult(
            "postgres", "failed",
            'psycopg2 is not installed - pip install "skewproof[postgres]"',
        )

    try:
        conn = psycopg2.connect(dsn)
    except Exception as exc:
        return CheckResult("postgres", "failed", f"could not connect: {exc}")
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            (version,) = cur.fetchone()
    except Exception as exc:
        return CheckResult("postgres", "failed", f"connected but query failed: {exc}")
    finally:
        conn.close()
    return CheckResult("postgres", "ok", version)


def check_redis(url: str | None = None) -> CheckResult:
    url = url if url is not None else os.environ.get("SKEWPROOF_REDIS_URL")
    if not url:
        return CheckResult("redis", "not_configured", "SKEWPROOF_REDIS_URL is not set")

    try:
        import redis
    except ImportError:
        return CheckResult(
            "redis", "failed",
            'redis is not installed - pip install "skewproof[redis]"',
        )

    try:
        client = redis.Redis.from_url(url)
    except Exception as exc:
        return CheckResult("redis", "failed", f"could not connect: {exc}")
    try:
        info = client.info("server")
    except Exception as exc:
        return CheckResult("redis", "failed", f"connected but query failed: {exc}")
    finally:
        try:
            client.close()
        except Exception:
            pass
    return CheckResult("redis", "ok", f"redis {info.get('redis_version', 'unknown')}")


def run_doctor() -> list[CheckResult]:
    """Run every check. Order is stable so CLI output is deterministic."""
    return [check_postgres(), check_redis()]
