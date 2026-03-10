from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple

from ontology.object_monitor.api.contracts import ObjectChangeEvent, PropertyChange, ReconcileEvent


@dataclass(frozen=True)
class NormalizationOutput:
    event: ObjectChangeEvent | None
    deduped: bool
    reconcile_event: ReconcileEvent | None = None


class ChangeNormalizer:
    """Normalize raw outbox/CDC events and dedupe by object version window."""

    def __init__(self, dedupe_window_seconds: int = 30) -> None:
        self._dedupe_window = timedelta(seconds=dedupe_window_seconds)
        self._recent_versions: Dict[Tuple[str, str, str, int], datetime] = {}
        self._latest_object_version: Dict[Tuple[str, str, str], int] = {}

    def normalize(self, raw_event: ObjectChangeEvent) -> NormalizationOutput:
        dedupe_key = (raw_event.tenant_id, raw_event.object_type, raw_event.object_id, raw_event.object_version)
        obj_key = (raw_event.tenant_id, raw_event.object_type, raw_event.object_id)

        event_time = raw_event.event_time
        if self._is_duplicate(dedupe_key, event_time):
            return NormalizationOutput(event=None, deduped=True)

        latest_version = self._latest_object_version.get(obj_key)
        if latest_version is not None and raw_event.object_version < latest_version:
            reconcile = ReconcileEvent(
                tenant_id=raw_event.tenant_id,
                object_type=raw_event.object_type,
                object_id=raw_event.object_id,
                expected_version=latest_version,
                actual_version=raw_event.object_version,
                reason="object_version_regression",
                trace_id=raw_event.trace_id,
            )
            return NormalizationOutput(event=None, deduped=False, reconcile_event=reconcile)

        normalized_properties = self._normalize_properties(raw_event.changed_properties)
        normalized_fields = sorted(set(raw_event.changed_fields + [item.field for item in normalized_properties]))
        normalized = ObjectChangeEvent(
            event_id=raw_event.event_id,
            tenant_id=raw_event.tenant_id,
            object_type=raw_event.object_type,
            object_id=raw_event.object_id,
            source_version=raw_event.source_version,
            object_version=raw_event.object_version,
            changed_fields=normalized_fields,
            event_time=raw_event.event_time,
            trace_id=raw_event.trace_id,
            change_source=raw_event.change_source,
            changed_properties=normalized_properties,
        )
        self._recent_versions[dedupe_key] = event_time
        self._latest_object_version[obj_key] = raw_event.object_version
        self._evict_old_records(event_time)
        return NormalizationOutput(event=normalized, deduped=False)

    def _is_duplicate(self, key: Tuple[str, str, str, int], event_time: datetime) -> bool:
        previous = self._recent_versions.get(key)
        if previous is None:
            return False
        return abs(event_time - previous) <= self._dedupe_window

    def _evict_old_records(self, now: datetime) -> None:
        expired = [key for key, ts in self._recent_versions.items() if now - ts > self._dedupe_window]
        for key in expired:
            del self._recent_versions[key]


    def _normalize_properties(self, properties: list[PropertyChange]) -> list[PropertyChange]:
        """Deduplicate property changes by field and keep deterministic field order."""
        latest_by_field: dict[str, PropertyChange] = {}
        for item in properties:
            latest_by_field[item.field] = item
        return [latest_by_field[field] for field in sorted(latest_by_field.keys())]
