"""
Batch materialization: run MaterializationJob for several features - a whole
registry, or a chosen subset - against one online store in a single call.

A single MaterializationJob ties one feature to one EventSource, because two
features rarely share the exact same table or file. A batch run just needs a
source per feature, not one common source, so the caller passes a
{feature_name: EventSource} mapping. This fails fast, before writing anything,
if a requested feature has no source in that mapping - silently skipping a
feature you meant to materialize is exactly the kind of thing that turns into a
production incident days later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .definition import FeatureRegistry
from .materialize import MaterializationJob, MaterializationReport
from .offline import EventSource
from .redis_store import OnlineStoreProtocol


@dataclass(frozen=True)
class BatchMaterializationReport:
    """One MaterializationReport per feature that was run, in the order run."""

    reports: tuple[MaterializationReport, ...]

    @property
    def is_complete(self) -> bool:
        """True when every feature in the batch was itself complete."""
        return len(self.reports) > 0 and all(r.is_complete for r in self.reports)

    @property
    def feature_names(self) -> tuple[str, ...]:
        return tuple(r.feature_name for r in self.reports)


class BatchMaterializationJob:
    """Runs MaterializationJob for several features against one online store."""

    def __init__(self, online: OnlineStoreProtocol) -> None:
        self._online = online

    def run(
        self,
        registry: FeatureRegistry,
        sources: dict[str, EventSource],
        entity_ids: list[str] | dict[str, list[str]],
        as_of: datetime,
        feature_names: list[str] | None = None,
    ) -> BatchMaterializationReport:
        """Materialize feature_names (default: every feature in registry).

        entity_ids is either one list shared by every feature in the batch, or
        a {feature_name: entity_ids} mapping when different features need
        different entities.
        """
        names = feature_names if feature_names is not None else [d.name for d in registry.all()]

        missing_sources = [n for n in names if n not in sources]
        if missing_sources:
            raise ValueError(
                f"no source given for feature(s): {', '.join(sorted(missing_sources))}"
            )
        if isinstance(entity_ids, dict):
            missing_entities = [n for n in names if n not in entity_ids]
            if missing_entities:
                raise ValueError(
                    f"no entity_ids given for feature(s): {', '.join(sorted(missing_entities))}"
                )

        reports = []
        for name in names:
            definition = registry.get(name)
            entities = entity_ids[name] if isinstance(entity_ids, dict) else entity_ids
            job = MaterializationJob(self._online, sources[name])
            reports.append(job.run(definition, entities, as_of))
        return BatchMaterializationReport(tuple(reports))
