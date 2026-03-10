from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict
from urllib import error, request

from ontology.object_monitor.api.contracts import ObjectChangeEvent, PropertyChange


@dataclass(frozen=True)
class Neo4jKafkaSourceConfig:
    """Config model for Neo4j Kafka Source Connector in CDC strategy."""

    connector_name: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    kafka_topic: str
    cdc_patterns: list[str] = field(default_factory=lambda: ["(:Device)"])
    poll_interval: str = "1s"
    poll_duration: str = "5s"
    streaming_from: str = "NOW"

    def to_connector_payload(self) -> Dict[str, Any]:
        """Render Kafka Connect REST payload using official `neo4j.cdc.topic.<topic>.patterns` keys."""
        config: Dict[str, str] = {
            "connector.class": "org.neo4j.connectors.kafka.source.Neo4jConnector",
            "tasks.max": "1",
            "neo4j.server.uri": self.neo4j_uri,
            "neo4j.authentication.basic.username": self.neo4j_user,
            "neo4j.authentication.basic.password": self.neo4j_password,
            "neo4j.database": self.neo4j_database,
            "neo4j.source-strategy": "CDC",
            "neo4j.cdc.poll-interval": self.poll_interval,
            "neo4j.cdc.poll-duration": self.poll_duration,
            "neo4j.cdc.from": self.streaming_from,
            f"neo4j.cdc.topic.{self.kafka_topic}.patterns": ",".join(self.cdc_patterns),
            f"neo4j.cdc.topic.{self.kafka_topic}.key-strategy": "ELEMENT_ID",
            "key.converter": "org.apache.kafka.connect.storage.StringConverter",
            "value.converter": "org.apache.kafka.connect.json.JsonConverter",
            "value.converter.schemas.enable": "false",
        }
        return {"name": self.connector_name, "config": config}


class KafkaConnectClient:
    """Minimal Kafka Connect REST client for connector lifecycle automation."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def create_or_replace(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = str(payload["name"])
        try:
            return self._request_json("PUT", f"/connectors/{name}/config", payload["config"])
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"kafka-connect upsert failed: {exc.code} {body}") from exc

    def status(self, connector_name: str) -> Dict[str, Any]:
        return self._request_json("GET", f"/connectors/{connector_name}/status")

    def _request_json(self, method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self._base_url}{path}",
            method=method,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        with request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))


class Neo4jKafkaCdcEventMapper:
    """Map Neo4j Kafka CDC records to ObjectChangeEvent."""

    @staticmethod
    def from_neo4j_cdc_query_event(
        change: Dict[str, Any],
        tenant_id: str,
        object_type: str,
        object_id_field: str,
    ) -> ObjectChangeEvent:
        """Map output row from `CALL db.cdc.query` to ObjectChangeEvent."""
        event = change.get("event", {}) if isinstance(change.get("event"), dict) else {}
        metadata = change.get("metadata", {}) if isinstance(change.get("metadata"), dict) else {}
        state = event.get("state", {}) if isinstance(event.get("state"), dict) else {}
        before = state.get("before", {}) if isinstance(state.get("before"), dict) else {}
        after = state.get("after", {}) if isinstance(state.get("after"), dict) else {}
        changed = _property_diff(before, after)
        object_id = str(after.get(object_id_field) or before.get(object_id_field) or event.get("elementId") or change.get("id"))
        tx_id = str(change.get("id") or metadata.get("txId") or object_id)
        source_version = int(metadata.get("txSeq", change.get("seq", 0)) or 0)
        event_time = _to_datetime(metadata.get("txCommitTime") or change.get("txCommitTime") or change.get("eventTime"))

        return ObjectChangeEvent(
            event_id=tx_id,
            tenant_id=tenant_id,
            object_type=object_type,
            object_id=object_id,
            source_version=source_version,
            object_version=source_version,
            changed_fields=[row.field for row in changed],
            event_time=event_time,
            trace_id=tx_id,
            change_source="neo4j_cdc",
            changed_properties=changed,
        )

    @staticmethod
    def from_connector_message(value: Dict[str, Any], tenant_id: str, object_type: str, object_id_field: str) -> ObjectChangeEvent:
        event = value.get("event", {}) if isinstance(value.get("event"), dict) else {}
        metadata = value.get("metadata", {}) if isinstance(value.get("metadata"), dict) else {}
        state = event.get("state", {}) if isinstance(event.get("state"), dict) else {}
        before = state.get("before", {}) if isinstance(state.get("before"), dict) else {}
        after = state.get("after", {}) if isinstance(state.get("after"), dict) else {}

        object_id = str(after.get(object_id_field) or before.get(object_id_field) or event.get("elementId") or value.get("id"))
        changed = _property_diff(before, after)
        changed_fields = [row.field for row in changed]

        tx_id = str(value.get("id") or metadata.get("txId") or value.get("txId") or "")
        event_time = _to_datetime(value.get("timestamp") or metadata.get("txCommitTime") or value.get("eventTime"))
        source_version = int(metadata.get("txSeq", value.get("seq", 0)) or 0)
        object_version = int(metadata.get("txSeq", value.get("seq", 0)) or 0)

        return ObjectChangeEvent(
            event_id=tx_id or f"{object_type}:{object_id}:{source_version}",
            tenant_id=tenant_id,
            object_type=object_type,
            object_id=object_id,
            source_version=source_version,
            object_version=object_version,
            changed_fields=changed_fields,
            event_time=event_time,
            trace_id=tx_id or object_id,
            change_source="neo4j_cdc",
            changed_properties=changed,
        )


def _property_diff(before: Dict[str, Any], after: Dict[str, Any]) -> list[PropertyChange]:
    fields = sorted(set(before.keys()) | set(after.keys()))
    rows: list[PropertyChange] = []
    for field in fields:
        old = before.get(field)
        new = after.get(field)
        if old != new:
            rows.append(PropertyChange(field=field, old_value=old, new_value=new))
    return rows


def _to_datetime(value: Any):
    from datetime import datetime

    if value is None:
        return datetime.utcnow()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
