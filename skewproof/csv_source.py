"""
A CSV-backed EventSource.

Reads (event_ts, value) rows for one entity from a plain CSV file with a header
row. This exists for local development and onboarding: no database to stand up,
no dependency beyond the standard library's csv module - just a file.

Same contract as InMemoryEventSource and SqlEventSource: rows_for returns the
full, unfiltered history for one entity. The point-in-time filter still lives in
FeatureDefinition.reduce(), not here. Keeping the source "dumb" is deliberate:
one place owns the time logic, regardless of where the rows came from.

The whole file is scanned on every call, filtering to just the requested entity.
That's the right tradeoff for what this class is for (a handful of megabytes on a
laptop); once scanning the whole file on every entity lookup is the bottleneck,
that's the signal to reach for SqlEventSource instead.
"""
from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class CsvEventSource:
    """Reads events for one entity from a CSV file with a header row.

    path:              path to the CSV file
    entity_column:     header name of the column identifying the entity
    timestamp_column:  header name of the event-time column (ISO 8601)
    value_column:      header name of the numeric value column
    """

    path: str | Path
    entity_column: str
    timestamp_column: str
    value_column: str

    def __post_init__(self) -> None:
        for field_name in ("entity_column", "timestamp_column", "value_column"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} is required")

    def rows_for(self, entity_id: str) -> list[tuple[datetime, float]]:
        rows: list[tuple[datetime, float]] = []
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self._check_header(reader.fieldnames)
            for record in reader:
                if record[self.entity_column] != entity_id:
                    continue
                ts = datetime.fromisoformat(record[self.timestamp_column])
                value = float(record[self.value_column])
                rows.append((ts, value))
        return rows

    def _check_header(self, fieldnames: Sequence[str] | None) -> None:
        header = fieldnames or []
        missing = [
            c
            for c in (self.entity_column, self.timestamp_column, self.value_column)
            if c not in header
        ]
        if missing:
            raise ValueError(
                f"CSV at {self.path} is missing column(s): {', '.join(missing)}"
            )
