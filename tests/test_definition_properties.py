"""
Property-based tests for FeatureDefinition.reduce().

tests/test_definition.py checks reduce() against handwritten examples. This file
checks it against invariants that should hold for *any* rows/as_of/aggregation -
Hypothesis generates hundreds of random cases per run and shrinks any failure to
a minimal reproducing example. This is aimed squarely at reduce()'s job: turning
arbitrary history into one honest, point-in-time value.

Each property is written from the documented contract (the reduce() docstring
and FeatureDefinition's field docs), not by re-deriving reduce()'s own source -
a test that mirrors the implementation's logic would pass even if that logic
were wrong in the same way twice.
"""
from __future__ import annotations

import math
from datetime import datetime

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from skewproof.definition import Aggregation, FeatureDefinition

_datetimes = st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2035, 1, 1))
_values = st.floats(
    allow_nan=False, allow_infinity=False, min_value=-1e6, max_value=1e6, width=32
)
_rows = st.lists(st.tuples(_datetimes, _values), max_size=25)
_aggregations = st.sampled_from(list(Aggregation))
_window_seconds = st.integers(min_value=1, max_value=10_000_000)


def make_def(aggregation: Aggregation, window_seconds: int | None = None) -> FeatureDefinition:
    return FeatureDefinition(
        name="f", source="s", entity_key="e", timestamp_key="t", value_key="v",
        aggregation=aggregation, window_seconds=window_seconds,
    )


def visible_count(rows: list[tuple[datetime, float]], as_of: datetime) -> int:
    return len([1 for ts, _ in rows if ts <= as_of])


class TestNoFutureLeakage:
    @given(rows=_rows, as_of=_datetimes, agg=_aggregations)
    def test_rows_after_as_of_never_change_the_result(self, rows, as_of, agg) -> None:
        """The defining property of point-in-time correctness: dropping every row
        after as_of before calling reduce() must be a no-op, because reduce()
        should already have ignored them."""
        definition = make_def(agg)
        with_future_rows = definition.reduce(rows, as_of)
        past_only = [(ts, v) for ts, v in rows if ts <= as_of]
        without_future_rows = definition.reduce(past_only, as_of)
        assert with_future_rows == without_future_rows


class TestOrderIndependence:
    @given(rows=_rows, as_of=_datetimes, agg=_aggregations, data=st.data())
    def test_shuffling_input_rows_does_not_change_the_result(
        self, rows, as_of, agg, data
    ) -> None:
        shuffled = data.draw(st.permutations(rows))
        definition = make_def(agg)
        assert definition.reduce(rows, as_of) == definition.reduce(shuffled, as_of)


class TestNoneMeansNoVisibleData:
    @given(rows=_rows, as_of=_datetimes, agg=_aggregations)
    def test_none_iff_nothing_is_visible(self, rows, as_of, agg) -> None:
        definition = make_def(agg)
        result = definition.reduce(rows, as_of)
        assert (result is None) == (visible_count(rows, as_of) == 0)


class TestCount:
    @given(rows=_rows, as_of=_datetimes)
    def test_count_equals_the_number_of_visible_rows(self, rows, as_of) -> None:
        result = make_def(Aggregation.COUNT).reduce(rows, as_of)
        n = visible_count(rows, as_of)
        assert result == (float(n) if n > 0 else None)


class TestSumMeanCountAgree:
    @given(rows=_rows, as_of=_datetimes)
    def test_sum_equals_mean_times_count(self, rows, as_of) -> None:
        n = visible_count(rows, as_of)
        assume(n > 0)
        total = make_def(Aggregation.SUM).reduce(rows, as_of)
        mean = make_def(Aggregation.MEAN).reduce(rows, as_of)
        count = make_def(Aggregation.COUNT).reduce(rows, as_of)
        assert count == float(n)
        assert math.isclose(total, mean * count, rel_tol=1e-4, abs_tol=1e-3)


class TestMinMeanMaxOrdering:
    @given(rows=_rows, as_of=_datetimes)
    def test_min_le_mean_le_max(self, rows, as_of) -> None:
        assume(visible_count(rows, as_of) > 0)
        lo = make_def(Aggregation.MIN).reduce(rows, as_of)
        hi = make_def(Aggregation.MAX).reduce(rows, as_of)
        mean = make_def(Aggregation.MEAN).reduce(rows, as_of)
        assert lo <= mean + 1e-3
        assert mean <= hi + 1e-3
        assert lo <= hi


class TestLatest:
    @given(rows=_rows, as_of=_datetimes)
    def test_latest_is_the_value_at_the_max_visible_timestamp(self, rows, as_of) -> None:
        visible = [(ts, v) for ts, v in rows if ts <= as_of]
        assume(visible)
        result = make_def(Aggregation.LATEST).reduce(rows, as_of)
        max_ts = max(ts for ts, _ in visible)
        candidates = {v for ts, v in visible if ts == max_ts}
        assert result in candidates


class TestWindow:
    @given(rows=_rows, as_of=_datetimes, window=_window_seconds, agg=_aggregations)
    def test_window_matches_an_independently_filtered_reference(
        self, rows, as_of, window, agg
    ) -> None:
        """Written from the documented semantics (window_seconds is "an optional
        lookback ending at as_of"), independently of reduce()'s own filter code,
        so a boundary bug in reduce() has to agree with a second implementation
        of the same rule to pass."""
        windowed = make_def(agg, window_seconds=window).reduce(rows, as_of)

        lo = as_of.timestamp() - window
        reference_rows = [(ts, v) for ts, v in rows if ts <= as_of and ts.timestamp() >= lo]
        reference = make_def(agg).reduce(reference_rows, as_of)

        assert windowed == reference

    @given(as_of=_datetimes, window=_window_seconds, value=_values, agg=_aggregations)
    def test_row_exactly_at_the_lower_window_boundary_is_included(
        self, as_of, window, value, agg
    ) -> None:
        """A row landing exactly on as_of - window_seconds is a single point in
        the space of possible timestamps, so random generation essentially never
        produces it - this pins that boundary down explicitly rather than hoping
        the differential test above stumbles onto it. Regressing the '>=' in
        reduce()'s window filter to '>' would drop this row silently, and the
        general property test would very rarely notice."""
        boundary = datetime.fromtimestamp(as_of.timestamp() - window)
        rows = [(boundary, value)]
        result = make_def(agg, window_seconds=window).reduce(rows, as_of)
        assert result is not None


class TestValidation:
    @given(window=st.integers(max_value=0))
    def test_non_positive_window_seconds_always_rejected(self, window) -> None:
        with pytest.raises(ValueError, match="window_seconds must be positive"):
            FeatureDefinition(
                name="f", source="s", entity_key="e", timestamp_key="t", value_key="v",
                window_seconds=window,
            )
