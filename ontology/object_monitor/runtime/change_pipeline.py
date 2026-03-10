from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Protocol

from ontology.object_monitor.api.contracts import ObjectChangeEvent, PropertyChange, ReconcileEvent
from ontology.object_monitor.runtime.normalizer import ChangeNormalizer


class RawEventSink(Protocol):
    """Abstraction for publishing raw change events before normalization."""

    def publish(self, event: ObjectChangeEvent) -> None: ...


@dataclass
class InMemoryRawEventBus(RawEventSink):
    """Simple in-process raw event sink used by tests and local runs."""

    events: List[ObjectChangeEvent]

    def __init__(self) -> None:
        self.events = []

    def publish(self, event: ObjectChangeEvent) -> None:
        """Append an event to the in-memory buffer."""
        self.events.append(event)


class Neo4jCdcMapper:
    """Map Neo4j CDC row payloads to ObjectChangeEvent envelope."""

    @staticmethod
    def from_cdc_payload(payload: dict) -> ObjectChangeEvent:
        """Convert a Neo4j CDC payload into the canonical object monitor event."""
        changed_properties = _extract_changed_properties(payload)
        changed_fields = [c.field for c in changed_properties] or [str(f) for f in payload.get("changedFields", [])]
        return ObjectChangeEvent(
            event_id=str(payload["txId"]),
            tenant_id=str(payload["tenantId"]),
            object_type=str(payload["label"]),
            object_id=str(payload["primaryKey"]),
            source_version=int(payload["sourceVersion"]),
            object_version=int(payload["objectVersion"]),
            changed_fields=changed_fields,
            event_time=_dt(payload["eventTime"]),
            trace_id=str(payload.get("traceId", payload["txId"])),
            change_source="neo4j_cdc",
            changed_properties=changed_properties,
        )


@dataclass(frozen=True)
class PipelineResult:
    """Result summary of a dual-channel ingestion batch."""

    normalized_events: List[ObjectChangeEvent]
    deduped_count: int
    reconcile_events: List[ReconcileEvent]


class DualChannelIngestionPipeline:
    """Ingest outbox + CDC events, publish raw, normalize/dedupe, and route reconcile events."""

    def __init__(self, normalizer: ChangeNormalizer, raw_sink: RawEventSink | None = None) -> None:
        """Create a pipeline with pluggable normalizer and raw sink."""
        self._normalizer = normalizer
        self._raw_sink = raw_sink or InMemoryRawEventBus()

    def ingest(self, outbox_events: Iterable[ObjectChangeEvent], cdc_events: Iterable[ObjectChangeEvent]) -> PipelineResult:
        """Merge outbox and CDC events, then normalize, dedupe and collect reconciliations."""
        normalized: list[ObjectChangeEvent] = []
        deduped = 0
        reconcile: list[ReconcileEvent] = []
        index_by_key: dict[tuple[str, str, str, int], int] = {}

        for event in [*outbox_events, *cdc_events]:
            self._raw_sink.publish(event)
            result = self._normalizer.normalize(event)
            key = (event.tenant_id, event.object_type, event.object_id, event.object_version)
            if result.deduped:
                deduped += 1
                idx = index_by_key.get(key)
                if idx is not None and event.changed_properties:
                    existing = normalized[idx]
                    normalized[idx] = ObjectChangeEvent(
                        event_id=existing.event_id,
                        tenant_id=existing.tenant_id,
                        object_type=existing.object_type,
                        object_id=existing.object_id,
                        source_version=existing.source_version,
                        object_version=existing.object_version,
                        changed_fields=sorted(set(existing.changed_fields + [c.field for c in event.changed_properties])),
                        event_time=existing.event_time,
                        trace_id=existing.trace_id,
                        change_source=existing.change_source,
                        changed_properties=sorted(event.changed_properties, key=lambda c: c.field),
                    )
            if result.event is not None:
                index_by_key[key] = len(normalized)
                normalized.append(result.event)
            if result.reconcile_event is not None:
                reconcile.append(result.reconcile_event)

        return PipelineResult(normalized_events=normalized, deduped_count=deduped, reconcile_events=reconcile)


def _dt(value: object) -> datetime:
    """Normalize either datetime objects or ISO strings into datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _extract_changed_properties(payload: dict) -> list[PropertyChange]:
    """Extract field-level old/new values from connector payload variants."""
    # Preferred envelope: changedProperties=[{"field":"temperature","old":70,"new":85}]
    properties: list[PropertyChange] = []
    for row in payload.get("changedProperties", []) or []:
        field = str(row.get("field") or row.get("name") or "")
        if not field:
            continue
        properties.append(PropertyChange(field=field, old_value=row.get("old"), new_value=row.get("new")))

    # Fallback envelope used by some CDC pipelines: before/after maps.
    if properties:
        return properties
    before = payload.get("before")
    after = payload.get("after")
    if isinstance(before, dict) and isinstance(after, dict):
        keys = sorted(set(before.keys()) | set(after.keys()))
        for key in keys:
            if before.get(key) != after.get(key):
                properties.append(PropertyChange(field=str(key), old_value=before.get(key), new_value=after.get(key)))
    return properties
