from datetime import datetime

from ontology.object_monitor.api.contracts import ObjectChangeEvent
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import ContextBuilder, EventFilter, MonitorRuntimeSpec, Neo4jQueryContextStore


def _event(changed_fields: list[str], object_version: int = 11) -> ObjectChangeEvent:
    return ObjectChangeEvent(
        event_id="evt-1",
        tenant_id="t1",
        object_type="Device",
        object_id="D100",
        source_version=901,
        object_version=object_version,
        changed_fields=changed_fields,
        event_time=datetime(2026, 1, 2, 10, 0, 0),
        trace_id="tr-1",
        change_source="outbox",
    )


def _artifact(monitor_id: str, *, scope: str = "", condition: str = "temperature >= 80 && status == 'RUNNING'"):
    payload = {
        "monitor": {"id": monitor_id, "objectType": "Device", "scope": scope},
        "input": {"fields": ["temperature", "status", "plant_id"]},
        "condition": {"expr": condition},
        "effect": {
            "action": {
                "endpoint": "action://ticket/create",
                "idempotencyKey": "${monitorId}:${objectId}:${sourceVersion}",
            }
        },
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def test_w3_context_builder_materializes_main_and_one_hop_fields() -> None:
    builder = ContextBuilder()
    event = _event(["temperature", "status"])

    snapshot = builder.build(
        event,
        object_payload={"temperature": 88, "status": "RUNNING", "plant_id": "P1"},
        related_payloads={"owner": {"name": "alice", "level": "L2"}},
    )

    assert snapshot.object_version == event.object_version
    assert snapshot.source_version == event.source_version
    assert snapshot.payload["temperature"] == 88
    assert snapshot.payload["owner_name"] == "alice"
    assert snapshot.payload["owner_level"] == "L2"

    stored = builder.store.get("t1", "Device", "D100")
    assert stored is not None
    assert stored.payload == snapshot.payload


def test_w3_event_filter_applies_changed_fields_and_scope() -> None:
    event_filter = EventFilter()
    hot_monitor = _artifact("m_hot", scope="plant_id in ['P1','P2']")
    cold_monitor = _artifact("m_cold", scope="plant_id == 'P9'")

    event_filter.load_specs(
        [
            MonitorRuntimeSpec(artifact=hot_monitor, object_type="Device", watched_fields={"temperature"}),
            MonitorRuntimeSpec(artifact=cold_monitor, object_type="Device", watched_fields={"status"}),
        ]
    )

    event = _event(["temperature"])
    candidates = event_filter.filter_candidates(event, {"plant_id": "P1", "status": "RUNNING"})
    assert [a.monitor_id for a in candidates] == ["m_hot"]


def test_w3_event_filter_supports_hot_reload() -> None:
    event_filter = EventFilter()
    first = _artifact("m_first", scope="plant_id == 'P1'")
    second = _artifact("m_second", scope="plant_id == 'P2'")

    event_filter.load_specs([MonitorRuntimeSpec(artifact=first, object_type="Device", watched_fields={"status"})])
    event = _event(["status"])
    assert [a.monitor_id for a in event_filter.filter_candidates(event, {"plant_id": "P1"})] == ["m_first"]

    event_filter.load_specs([MonitorRuntimeSpec(artifact=second, object_type="Device", watched_fields={"status"})])
    assert [a.monitor_id for a in event_filter.filter_candidates(event, {"plant_id": "P2"})] == ["m_second"]


def test_context_provider_can_query_neo4j_fallback_without_kv() -> None:
    store = Neo4jQueryContextStore(
        lambda **_: {
            "object_version": 12,
            "source_version": 901,
            "temperature": 85,
            "status": "RUNNING",
            "plant_id": "P1",
        }
    )
    snapshot = store.get("t1", "Device", "D100")
    assert snapshot is not None
    assert snapshot.object_version == 12
    assert snapshot.payload["temperature"] == 85
