from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Protocol

from ontology.object_monitor.define.api.contracts import ObjectChangeEvent, ReconcileEvent
from ontology.object_monitor.runtime.capture.normalizer import ChangeNormalizer


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


@dataclass(frozen=True)
class PipelineResult:
    """Result summary of a dual-channel ingestion batch."""

    normalized_events: List[ObjectChangeEvent]
    deduped_count: int
    reconcile_events: List[ReconcileEvent]


class DualChannelIngestionPipeline:
    """Ingest outbox + secondary events, publish raw, normalize/dedupe, and route reconcile events."""

    def __init__(self, normalizer: ChangeNormalizer, raw_sink: RawEventSink | None = None) -> None:
        """Create a pipeline with pluggable normalizer and raw sink."""
        self._normalizer = normalizer
        self._raw_sink = raw_sink or InMemoryRawEventBus()

    def ingest(self, outbox_events: Iterable[ObjectChangeEvent], secondary_events: Iterable[ObjectChangeEvent]) -> PipelineResult:
        """Merge outbox and secondary events, then normalize, dedupe and collect reconciliations."""
        normalized: list[ObjectChangeEvent] = []
        deduped = 0
        reconcile: list[ReconcileEvent] = []
        index_by_key: dict[tuple[str, str, str, int], int] = {}

        for event in [*outbox_events, *secondary_events]:
            self._raw_sink.publish(event)
            result = self._normalizer.normalize(event)
            key = (event.tenant_id, event.object_type, event.object_id, event.object_version)
            if result.deduped:
                deduped += 1
                idx = index_by_key.get(key)
                if idx is not None and event.changed_properties:
                    existing = normalized[idx]
                    merged_props = {
                        item.field: item for item in [*existing.changed_properties, *event.changed_properties]
                    }
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
                        changed_properties=[merged_props[field] for field in sorted(merged_props.keys())],
                    )
            if result.event is not None:
                index_by_key[key] = len(normalized)
                normalized.append(result.event)
            if result.reconcile_event is not None:
                reconcile.append(result.reconcile_event)

        return PipelineResult(normalized_events=normalized, deduped_count=deduped, reconcile_events=reconcile)


class SingleChannelIngestionPipeline:
    """Phase-1 trimmed ingestion pipeline for Streams/APOC single source."""

    def __init__(self, normalizer: ChangeNormalizer, raw_sink: RawEventSink | None = None) -> None:
        self._normalizer = normalizer
        self._raw_sink = raw_sink or InMemoryRawEventBus()

    def ingest(self, events: Iterable[ObjectChangeEvent]) -> PipelineResult:
        normalized: list[ObjectChangeEvent] = []
        deduped = 0
        reconcile: list[ReconcileEvent] = []

        for event in events:
            self._raw_sink.publish(event)
            result = self._normalizer.normalize(event)
            if result.deduped:
                deduped += 1
                continue
            if result.event is not None:
                normalized.append(result.event)
            if result.reconcile_event is not None:
                reconcile.append(result.reconcile_event)

        return PipelineResult(normalized_events=normalized, deduped_count=deduped, reconcile_events=reconcile)

