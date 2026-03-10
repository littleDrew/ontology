from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from ontology.object_monitor.api.contracts import ObjectChangeEvent, PropertyChange


class Neo4jStreamsEventMapper:
    """Map Neo4j Streams-style messages to ObjectChangeEvent."""

    @staticmethod
    def from_streams_message(
        value: Dict[str, Any],
        *,
        tenant_id: str,
        object_type: str,
        object_id_field: str,
    ) -> ObjectChangeEvent:
        meta = value.get("meta", {}) if isinstance(value.get("meta"), dict) else {}
        payload = value.get("payload", {}) if isinstance(value.get("payload"), dict) else {}

        before = _extract_properties(payload.get("before"))
        after = _extract_properties(payload.get("after"))
        changed_properties = _property_diff(before, after)

        object_id = str(
            after.get(object_id_field)
            or before.get(object_id_field)
            or payload.get("id")
            or value.get("id")
            or ""
        )
        source_version = int(meta.get("txSeq") or meta.get("txId") or value.get("seq") or 0)
        event_id = str(meta.get("txId") or value.get("id") or f"streams:{object_type}:{object_id}:{source_version}")

        return ObjectChangeEvent(
            event_id=event_id,
            tenant_id=tenant_id,
            object_type=object_type,
            object_id=object_id,
            source_version=source_version,
            object_version=source_version,
            changed_fields=[row.field for row in changed_properties],
            event_time=_to_datetime(meta.get("timestamp") or value.get("timestamp")),
            trace_id=event_id,
            change_source="neo4j_streams",
            changed_properties=changed_properties,
        )


def _extract_properties(node_payload: Any) -> Dict[str, Any]:
    if isinstance(node_payload, dict):
        props = node_payload.get("properties")
        if isinstance(props, dict):
            return props
        return node_payload if all(isinstance(k, str) for k in node_payload.keys()) else {}
    return {}


def _property_diff(before: Dict[str, Any], after: Dict[str, Any]) -> list[PropertyChange]:
    fields = sorted(set(before.keys()) | set(after.keys()))
    rows: list[PropertyChange] = []
    for field in fields:
        old = before.get(field)
        new = after.get(field)
        if old != new:
            rows.append(PropertyChange(field=field, old_value=old, new_value=new))
    return rows


def _to_datetime(value: Any) -> datetime:
    if value is None:
        return datetime.utcnow()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
