from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Protocol

from ontology.object_monitor.api.contracts import ObjectChangeEvent, ReconcileEvent
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
        return ObjectChangeEvent(
            event_id=str(payload["txId"]),
            tenant_id=str(payload["tenantId"]),
            object_type=str(payload["label"]),
            object_id=str(payload["primaryKey"]),
            source_version=int(payload["sourceVersion"]),
            object_version=int(payload["objectVersion"]),
            changed_fields=[str(f) for f in payload.get("changedFields", [])],
            event_time=_dt(payload["eventTime"]),
            trace_id=str(payload.get("traceId", payload["txId"])),
            change_source="neo4j_cdc",
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

        for event in [*outbox_events, *cdc_events]:
            self._raw_sink.publish(event)
            result = self._normalizer.normalize(event)
            if result.deduped:
                deduped += 1
            if result.event is not None:
                normalized.append(result.event)
            if result.reconcile_event is not None:
                reconcile.append(result.reconcile_event)

        return PipelineResult(normalized_events=normalized, deduped_count=deduped, reconcile_events=reconcile)


def _dt(value: object) -> datetime:
    """Normalize either datetime objects or ISO strings into datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
