"""
Backfill: run MaterializationJob for one feature across a range of as_of
instants, in order, collecting a MaterializationReport per step.

Every online store in skewproof holds one current value per (feature, entity) -
there's no multi-snapshot history in the store itself (see materialize.py's
module docstring). So after a backfill, only the last as_of's values are what's
actually served; the earlier steps aren't retained anywhere except in the
BackfillReport this returns.

That's still useful for two real things:

  Incremental population. Materializing straight to a far-future as_of in one
  call is one big, all-or-nothing write. Backfilling day by day up to that same
  as_of is the same end state, but a crash partway through leaves the store at a
  valid earlier as_of instead of a half-written one, and each step is cheaper to
  retry than the whole range.

  Historical audit. Walking as_of backward through history and looking at each
  step's values_unknown is how you'd notice "coverage for this feature was fine
  until three weeks ago" - a gap in an upstream feed that a single as_of='now'
  materialization would never surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .definition import FeatureDefinition
from .materialize import MaterializationJob, MaterializationReport
from .offline import EventSource
from .redis_store import OnlineStoreProtocol


@dataclass(frozen=True)
class BackfillReport:
    """One MaterializationReport per as_of that was run, in chronological order
    (the order given to BackfillJob.run - it does not sort them for you)."""

    reports: tuple[MaterializationReport, ...]

    @property
    def is_complete(self) -> bool:
        """True when every step was itself complete."""
        return len(self.reports) > 0 and all(r.is_complete for r in self.reports)

    @property
    def as_of_values(self) -> tuple[datetime, ...]:
        return tuple(r.as_of for r in self.reports)

    def incomplete_steps(self) -> tuple[MaterializationReport, ...]:
        """Reports for the as_of values with at least one unknown entity - the
        steps worth investigating first when auditing a feature's history."""
        return tuple(r for r in self.reports if not r.is_complete)


class BackfillJob:
    """Runs MaterializationJob for one feature across a range of as_of instants."""

    def __init__(self, online: OnlineStoreProtocol, source: EventSource) -> None:
        self._job = MaterializationJob(online, source)

    def run(
        self,
        definition: FeatureDefinition,
        entity_ids: list[str],
        as_of_values: list[datetime],
    ) -> BackfillReport:
        if not as_of_values:
            raise ValueError("as_of_values must not be empty")
        reports = tuple(
            self._job.run(definition, entity_ids, as_of) for as_of in as_of_values
        )
        return BackfillReport(reports)


def daily_range(start: datetime, end: datetime) -> list[datetime]:
    """Every day from start to end inclusive, same time-of-day as start.

    A small helper for the common case - one as_of per day. Build the list by
    hand and pass it to BackfillJob.run() directly for any other cadence
    (hourly, business days only, etc).
    """
    if end < start:
        raise ValueError("end must not be before start")
    values = []
    current = start
    while current <= end:
        values.append(current)
        current += timedelta(days=1)
    return values
