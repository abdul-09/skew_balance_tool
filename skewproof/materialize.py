"""
The materialization job: push feature values from the offline source into the
online store so serving is a fast key lookup instead of a recompute.

This is the offline-to-online sync that feature stores name as the operationally
tricky part. Two properties matter here:

  Idempotent. Running the same job twice with the same as_of leaves the online store
  in the same state. Materialization is a blind overwrite per (feature, entity), and
  the value is a deterministic function of (source rows, as_of), so a re-run writes
  the same bytes. Safe to retry after a crash, safe to run on a schedule.

  Observable. The job returns a MaterializationReport saying what it wrote and how
  many values were unknown (None). A silent sync is a sync you cannot trust in
  production, so the job hands back a record you can log or assert on. It also
  emits its own log records (via the standard "skewproof.materialize" logger) so
  a run's progress and any unknown values are visible without the caller having
  to remember to log the returned report themselves. skewproof never configures
  logging handlers or levels itself; the embedding application decides whether
  and where these records go.

The job holds no value logic. It calls OnlineStore.materialize, which calls reduce().
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from .definition import FeatureDefinition
from .offline import EventSource
from .redis_store import OnlineStoreProtocol

# Library convention: get a module-level logger, but never configure it here
# (no handlers, no level, no basicConfig). The application embedding this job
# decides whether/where these records go; skewproof stays silent by default.
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MaterializationReport:
    """What one materialization run did. Returned so the caller can log or assert."""

    feature_name: str
    as_of: datetime
    entities_processed: int
    values_written: int   # entities with a known (non-None) value
    values_unknown: int   # entities whose feature was None at as_of

    @property
    def is_complete(self) -> bool:
        """True when every processed entity got a known value."""
        return self.entities_processed > 0 and self.values_unknown == 0


class MaterializationJob:
    """Syncs one feature's values for a set of entities into an online store."""

    def __init__(self, online: OnlineStoreProtocol, source: EventSource) -> None:
        self._online = online
        self._source = source

    def run(
        self,
        definition: FeatureDefinition,
        entity_ids: list[str],
        as_of: datetime,
    ) -> MaterializationReport:
        logger.info(
            "materializing feature=%s entities=%d as_of=%s",
            definition.name, len(entity_ids), as_of.isoformat(),
        )

        # Write everything through the store's materialize, so the value path is the
        # same reduce() used everywhere. Then read back to build an honest report.
        self._online.materialize(definition, self._source, entity_ids, as_of)

        written = 0
        unknown = 0
        for entity_id in entity_ids:
            if self._online.get(definition.name, entity_id) is None:
                unknown += 1
                logger.warning(
                    "unknown value feature=%s entity_id=%s as_of=%s",
                    definition.name, entity_id, as_of.isoformat(),
                )
            else:
                written += 1

        report = MaterializationReport(
            feature_name=definition.name,
            as_of=as_of,
            entities_processed=len(entity_ids),
            values_written=written,
            values_unknown=unknown,
        )
        logger.info(
            "materialized feature=%s entities=%d written=%d unknown=%d complete=%s",
            definition.name, report.entities_processed, report.values_written,
            report.values_unknown, report.is_complete,
        )
        return report
