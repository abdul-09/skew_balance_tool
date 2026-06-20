"""Tests for the demo loop and the CLI, both driven in-process."""
from __future__ import annotations

import io

import pytest

from skewproof import __version__
from skewproof.cli import main, build_parser
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
