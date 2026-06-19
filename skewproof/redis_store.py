"""
A Redis-backed online store.

Same contract as the in-process OnlineStore from commit 3: materialize() computes
each entity's value at an instant and writes it; get() reads it back. The only
difference is where the value lives. Serving code depends on the OnlineStoreProtocol
below, so it works against either store without change.

Values are written through the same FeatureDefinition.reduce() as every other path,
so a value served from Redis equals the training value for the same (entity, as_of).
Redis stores strings, so None (an unknown feature) is encoded explicitly rather than
being confused with a missing key.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from .definition import FeatureDefinition
from .offline import EventSource

# How None is stored, kept distinct from "key absent".
_NULL = "\x00null"


@runtime_checkable
class OnlineStoreProtocol(Protocol):
    """The serving contract shared by the in-process and Redis stores."""

    def materialize(
        self,
        definition: FeatureDefinition,
        source: EventSource,
        entity_ids: list[str],
        as_of: datetime,
    ) -> None:
        ...

    def get(self, feature_name: str, entity_id: str) -> float | None:
        ...


class RedisClient(Protocol):
    """The slice of redis-py we use. A real Redis client satisfies this."""

    def set(self, name: str, value: str) -> Any:
        ...

    def get(self, name: str) -> Any:
        ...


class RedisOnlineStore:
    """Serves features out of Redis. Construct with a redis.Redis client."""

    def __init__(self, client: RedisClient) -> None:
        self._client = client

    @staticmethod
    def _key(feature_name: str, entity_id: str) -> str:
        return f"skewproof:{feature_name}:{entity_id}"

    def materialize(
        self,
        definition: FeatureDefinition,
        source: EventSource,
        entity_ids: list[str],
        as_of: datetime,
    ) -> None:
        for entity_id in entity_ids:
            rows = source.rows_for(entity_id)
            value = definition.reduce(rows, as_of)
            stored = _NULL if value is None else repr(float(value))
            self._client.set(self._key(definition.name, entity_id), stored)

    def get(self, feature_name: str, entity_id: str) -> float | None:
        raw = self._client.get(self._key(feature_name, entity_id))
        if raw is None:
            return None  # key was never materialized
        text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
        if text == _NULL:
            return None  # materialized, but the feature value was unknown
        return float(text)
