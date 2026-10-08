"""Tests for the demo loop and the CLI, both driven in-process."""
from __future__ import annotations

import io

import pytest

from skewproof import __version__
from skewproof.cli import build_parser, main
from skewproof.demo import run_demo, seed_source, ts


class TestDemo:
    def test_no_skew_end_to_end(self) -> None:
        result = run_demo(ts(8))
        assert result.no_skew is True
        assert result.training == result.served

    def test_point_in_time_values(self) -> None:
        # As of day 8: farm_a latest is the day-7 reading (25.0), not day-11 (40.0).
        result = run_demo(ts(8))
        assert result.training["farm_a"] == 25.0
        assert result.training["farm_b"] == 15.0

    def test_future_reading_excluded(self) -> None:
        result = run_demo(ts(8))
        assert result.served["farm_a"] != 40.0  # day-11 reading is in the future

    def test_future_reading_included_later(self) -> None:
        result = run_demo(ts(12))
        assert result.served["farm_a"] == 40.0

    def test_default_as_of(self) -> None:
        # run_demo() with no argument defaults to day 8.
        assert run_demo().as_of == ts(8)

    def test_seed_source_shape(self) -> None:
        src = seed_source()
        assert src.rows_for("farm_a")[0] == (ts(1), 12.0)
        assert src.rows_for("farm_b") == [(ts(2), 8.0), (ts(6), 15.0)]


class TestCli:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        code = main(argv, buf)
        return code, buf.getvalue()

    def test_version(self) -> None:
        code, out = self._run(["version"])
        assert code == 0
        assert out.strip() == __version__

    def test_demo_default_day(self) -> None:
        code, out = self._run(["demo"])
        assert code == 0
        assert "as_of: 2026-01-08" in out
        assert "farm_a: 25.0" in out
        assert "no skew (training == served): True" in out

    def test_demo_custom_day(self) -> None:
        code, out = self._run(["demo", "--day", "12"])
        assert code == 0
        assert "as_of: 2026-01-12" in out
        assert "farm_a: 40.0" in out

    def test_demo_prints_both_sections(self) -> None:
        _, out = self._run(["demo"])
        assert "training values (point-in-time):" in out
        assert "served values (online store):" in out

    def test_no_command_errors(self) -> None:
        # Subcommand is required; argparse exits with code 2 on a parse error.
        with pytest.raises(SystemExit) as exc:
            self._run([])
        assert exc.value.code == 2

    def test_unknown_command_errors(self) -> None:
        with pytest.raises(SystemExit) as exc:
            self._run(["bogus"])
        assert exc.value.code == 2


class TestParser:
    def test_parser_builds(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["demo", "--day", "3"])
        assert args.command == "demo"
        assert args.day == 3


_CONFIG = '''
from skewproof.definition import Aggregation, FeatureRegistry, feature

registry = FeatureRegistry()

feature(
    registry,
    name="soil_latest",
    source="soil_readings",
    entity_key="farmer_id",
    timestamp_key="event_ts",
    value_key="moisture",
    aggregation=Aggregation.LATEST,
)
'''

_EMPTY_CONFIG = "from skewproof.definition import FeatureRegistry\nregistry = FeatureRegistry()\n"

_CSV = (
    "farmer_id,event_ts,moisture\n"
    "f1,2026-01-01T00:00:00,10.0\n"
    "f1,2026-01-05T00:00:00,30.0\n"
)


class TestCliList:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        code = main(argv, buf)
        return code, buf.getvalue()

    def test_lists_registered_features(self, tmp_path) -> None:
        config = tmp_path / "features.py"
        config.write_text(_CONFIG)
        code, out = self._run(["list", "--config", str(config)])
        assert code == 0
        assert "soil_latest" in out
        assert "source=soil_readings" in out
        assert "agg=latest" in out
        assert "window=all history" in out

    def test_empty_registry_prints_placeholder(self, tmp_path) -> None:
        config = tmp_path / "empty.py"
        config.write_text(_EMPTY_CONFIG)
        code, out = self._run(["list", "--config", str(config)])
        assert code == 0
        assert "no features registered" in out

    def test_config_error_reported(self, tmp_path) -> None:
        code, out = self._run(["list", "--config", str(tmp_path / "missing.py")])
        assert code == 1
        assert "error:" in out


class TestCliValidate:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        code = main(argv, buf)
        return code, buf.getvalue()

    def test_valid_config_reports_ok(self, tmp_path) -> None:
        config = tmp_path / "features.py"
        config.write_text(_CONFIG)
        code, out = self._run(["validate", "--config", str(config)])
        assert code == 0
        assert "OK: 1 feature(s) valid" in out

    def test_invalid_config_reports_error(self, tmp_path) -> None:
        code, out = self._run(["validate", "--config", str(tmp_path / "missing.py")])
        assert code == 1
        assert "invalid:" in out


class TestCliMaterialize:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        code = main(argv, buf)
        return code, buf.getvalue()

    def _write_config_and_csv(self, tmp_path) -> tuple[str, str]:
        config = tmp_path / "features.py"
        config.write_text(_CONFIG)
        csv_path = tmp_path / "readings.csv"
        csv_path.write_text(_CSV)
        return str(config), str(csv_path)

    def test_materialize_to_memory_store(self, tmp_path) -> None:
        config, csv_path = self._write_config_and_csv(tmp_path)
        code, out = self._run([
            "materialize", "--config", config, "--feature", "soil_latest",
            "--source-path", csv_path, "--entities", "f1",
            "--as-of", "2026-01-06T00:00:00",
        ])
        assert code == 0
        assert "values written: 1" in out
        assert "values unknown: 0" in out
        assert "complete: True" in out

    def test_materialize_unknown_entity_is_incomplete(self, tmp_path) -> None:
        config, csv_path = self._write_config_and_csv(tmp_path)
        code, out = self._run([
            "materialize", "--config", config, "--feature", "soil_latest",
            "--source-path", csv_path, "--entities", "ghost",
            "--as-of", "2026-01-06T00:00:00",
        ])
        assert code == 1
        assert "values unknown: 1" in out
        assert "complete: False" in out

    def test_materialize_multiple_entities(self, tmp_path) -> None:
        config, csv_path = self._write_config_and_csv(tmp_path)
        code, out = self._run([
            "materialize", "--config", config, "--feature", "soil_latest",
            "--source-path", csv_path, "--entities", "f1, ghost",
            "--as-of", "2026-01-06T00:00:00",
        ])
        assert code == 1
        assert "entities processed: 2" in out

    def test_materialize_bad_config_reports_error(self, tmp_path) -> None:
        _, csv_path = self._write_config_and_csv(tmp_path)
        code, out = self._run([
            "materialize", "--config", str(tmp_path / "missing.py"), "--feature", "soil_latest",
            "--source-path", csv_path, "--entities", "f1", "--as-of", "2026-01-06T00:00:00",
        ])
        assert code == 1
        assert "error:" in out

    def test_materialize_unknown_feature_reports_error(self, tmp_path) -> None:
        config, csv_path = self._write_config_and_csv(tmp_path)
        code, out = self._run([
            "materialize", "--config", config, "--feature", "does_not_exist",
            "--source-path", csv_path, "--entities", "f1", "--as-of", "2026-01-06T00:00:00",
        ])
        assert code == 1
        assert "error:" in out

    def test_materialize_bad_as_of_reports_error(self, tmp_path) -> None:
        config, csv_path = self._write_config_and_csv(tmp_path)
        code, out = self._run([
            "materialize", "--config", config, "--feature", "soil_latest",
            "--source-path", csv_path, "--entities", "f1", "--as-of", "not-a-timestamp",
        ])
        assert code == 1
        assert "invalid --as-of" in out

    def test_materialize_to_sqlite_store_persists(self, tmp_path) -> None:
        config, csv_path = self._write_config_and_csv(tmp_path)
        store_path = tmp_path / "features.db"
        code, out = self._run([
            "materialize", "--config", config, "--feature", "soil_latest",
            "--source-path", csv_path, "--store", "sqlite", "--store-path", str(store_path),
            "--entities", "f1", "--as-of", "2026-01-06T00:00:00",
        ])
        assert code == 0

        from skewproof.sqlite_store import SqliteOnlineStore

        with SqliteOnlineStore(str(store_path)) as reopened:
            assert reopened.get("soil_latest", "f1") == 30.0


class TestCliDoctor:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        code = main(argv, buf)
        return code, buf.getvalue()

    def test_reports_not_configured_when_env_vars_unset(self, monkeypatch) -> None:
        monkeypatch.delenv("SKEWPROOF_PG_DSN", raising=False)
        monkeypatch.delenv("SKEWPROOF_REDIS_URL", raising=False)
        code, out = self._run(["doctor"])
        assert code == 0
        assert "[--] postgres:" in out
        assert "[--] redis:" in out

    def test_reports_failed_and_exits_nonzero_when_configured_but_unusable(
        self, monkeypatch
    ) -> None:
        # psycopg2/redis genuinely aren't installed in this environment, so setting
        # the DSN/URL exercises the real "configured but can't connect" path.
        monkeypatch.setenv("SKEWPROOF_PG_DSN", "postgresql://x")
        monkeypatch.delenv("SKEWPROOF_REDIS_URL", raising=False)
        code, out = self._run(["doctor"])
        assert code == 1
        assert "[FAIL] postgres:" in out


class TestCliServe:
    def _run(self, argv: list[str]) -> tuple[int, str]:
        buf = io.StringIO()
        code = main(argv, buf)
        return code, buf.getvalue()

    def test_starts_the_server_with_a_memory_store(self, tmp_path, monkeypatch) -> None:
        config = tmp_path / "features.py"
        config.write_text(_CONFIG)

        calls = {}

        def fake_run_server(store, registry, host="127.0.0.1", port=8000):
            calls["store_type"] = type(store).__name__
            calls["registry"] = registry
            calls["host"] = host
            calls["port"] = port

        monkeypatch.setattr("skewproof.cli.run_server", fake_run_server)
        code, out = self._run(["serve", "--config", str(config)])

        assert code == 0
        assert "serving on http://127.0.0.1:8000" in out
        assert calls["store_type"] == "OnlineStore"
        assert calls["registry"].get("soil_latest") is not None

    def test_starts_the_server_with_a_sqlite_store(self, tmp_path, monkeypatch) -> None:
        config = tmp_path / "features.py"
        config.write_text(_CONFIG)
        store_path = tmp_path / "features.db"

        calls = {}
        monkeypatch.setattr(
            "skewproof.cli.run_server",
            lambda store, registry, host="127.0.0.1", port=8000: calls.update(
                store_type=type(store).__name__
            ),
        )
        code, _ = self._run([
            "serve", "--config", str(config), "--store", "sqlite",
            "--store-path", str(store_path),
        ])

        assert code == 0
        assert calls["store_type"] == "SqliteOnlineStore"

    def test_custom_host_and_port_are_forwarded(self, tmp_path, monkeypatch) -> None:
        config = tmp_path / "features.py"
        config.write_text(_CONFIG)

        calls = {}
        monkeypatch.setattr(
            "skewproof.cli.run_server",
            lambda store, registry, host="127.0.0.1", port=8000: calls.update(
                host=host, port=port
            ),
        )
        code, out = self._run([
            "serve", "--config", str(config), "--host", "0.0.0.0", "--port", "9001",
        ])

        assert code == 0
        assert calls == {"host": "0.0.0.0", "port": 9001}
        assert "serving on http://0.0.0.0:9001" in out

    def test_bad_config_reports_error_and_never_starts_server(
        self, tmp_path, monkeypatch
    ) -> None:
        called = False

        def fake_run_server(*args, **kwargs):
            nonlocal called
            called = True

        monkeypatch.setattr("skewproof.cli.run_server", fake_run_server)
        code, out = self._run(["serve", "--config", str(tmp_path / "missing.py")])

        assert code == 1
        assert "error:" in out
        assert called is False
