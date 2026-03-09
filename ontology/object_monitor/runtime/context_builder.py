from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping

from ontology.object_monitor.api.contracts import ObjectChangeEvent


@dataclass(frozen=True)
class ContextSnapshot:
    tenant_id: str
    object_type: str
    object_id: str
    object_version: int
    source_version: int
    payload: Dict[str, Any]
    updated_at: datetime


class InMemoryContextStore:
    def __init__(self) -> None:
        self._snapshots: Dict[str, ContextSnapshot] = {}

    @staticmethod
    def key_for(tenant_id: str, object_type: str, object_id: str) -> str:
        return f"{tenant_id}:{object_type}:{object_id}"

    def put(self, snapshot: ContextSnapshot) -> None:
        key = self.key_for(snapshot.tenant_id, snapshot.object_type, snapshot.object_id)
        self._snapshots[key] = snapshot

    def get(self, tenant_id: str, object_type: str, object_id: str) -> ContextSnapshot | None:
        return self._snapshots.get(self.key_for(tenant_id, object_type, object_id))


class ContextBuilder:
    """W3 context builder for copy mode: materialize main object + one-hop relation fields."""

    def __init__(self, store: InMemoryContextStore | None = None) -> None:
        self.store = store or InMemoryContextStore()

    def build(
        self,
        event: ObjectChangeEvent,
        *,
        object_payload: Mapping[str, Any],
        related_payloads: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> ContextSnapshot:
        related_payloads = related_payloads or {}
        flattened = dict(object_payload)
        for relation_alias, payload in related_payloads.items():
            for field_name, value in payload.items():
                flattened[f"{relation_alias}_{field_name}"] = value

        snapshot = ContextSnapshot(
            tenant_id=event.tenant_id,
            object_type=event.object_type,
            object_id=event.object_id,
            object_version=event.object_version,
            source_version=event.source_version,
            payload=flattened,
            updated_at=event.event_time,
        )
        self.store.put(snapshot)
        return snapshot
