import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from fastapi import FastAPI

from ontology.main import create_app
from ontology.instance.storage.graph_store import InMemoryGraphStore
from ontology.object_monitor.define.api.router import create_router as create_monitor_router
from ontology.object_monitor.define.api.service import InMemoryMonitorReleaseService
from ontology.object_monitor.define.api.contracts import ObjectChangeEvent
from ontology.object_monitor.runtime.event_filter import EventFilter
from datetime import datetime


def _payload(expr: str) -> dict:
    return {
        "general": {
            "name": "m_high_temp",
            "description": "high temp",
            "objectType": "Device",
            "enabled": True,
        },
        "condition": {
            "objectSet": {
                "type": "Device",
                "scope": "plant_id in ['P1','P2']",
                "properties": ["temperature", "status", "plant_id"],
            },
            "rule": {"expression": expr},
        },
        "actions": [
            {
                "name": "create_ticket",
                "actionRef": "action://ticket/create",
                "parameters": {"severity": "high"},
            }
        ],
    }


def test_control_plane_rest_publish_and_rollback() -> None:
    app = create_app(store=InMemoryGraphStore())
    client = TestClient(app)

    v1 = client.post(
        "/api/v1/monitors",
        json={
            "payload": _payload("temperature >= 80 && status == 'RUNNING'"),
            "available_fields": ["temperature", "status", "plant_id"],
            "operator": "alice",
        },
    )
    assert v1.status_code == 200
    assert v1.json()["status"] == "draft"

    v2 = client.post(
        "/api/v1/monitors",
        json={
            "payload": _payload("temperature >= 90 && status == 'RUNNING'"),
            "available_fields": ["temperature", "status", "plant_id"],
            "operator": "alice",
        },
    )
    assert v2.status_code == 200

    publish = client.post(
        f"/api/v1/monitors/m_high_temp/versions/{v2.json()['monitor_version']}/publish",
        json={"operator": "release-bot"},
    )
    assert publish.status_code == 200
    assert publish.json()["status"] == "active"

    rollback = client.post(
        "/api/v1/monitors/m_high_temp/rollback",
        json={"target_version": v1.json()["monitor_version"], "operator": "release-bot"},
    )
    assert rollback.status_code == 200
    assert rollback.json()["status"] == "active"
    assert rollback.json()["rollback_from_version"] == v1.json()["monitor_version"]


def test_publish_refreshes_event_filter_specs() -> None:
    service = InMemoryMonitorReleaseService()
    event_filter = EventFilter()
    app = FastAPI()
    app.include_router(create_monitor_router(service, event_filter), prefix="/api/v1")
    client = TestClient(app)

    created = client.post(
        "/api/v1/monitors",
        json={
            "payload": _payload("temperature >= 80 && status == 'RUNNING'"),
            "available_fields": ["temperature", "status", "plant_id"],
            "operator": "alice",
        },
    )
    assert created.status_code == 200

    publish = client.post(
        f"/api/v1/monitors/m_high_temp/versions/{created.json()['monitor_version']}/publish",
        json={"operator": "release-bot"},
    )
    assert publish.status_code == 200

    event = ObjectChangeEvent(
        event_id="evt-1",
        tenant_id="t1",
        object_type="Device",
        object_id="D1",
        source_version=1,
        object_version=1,
        changed_fields=["temperature"],
        event_time=datetime(2026, 1, 1, 0, 0, 0),
        trace_id="tr-1",
    )
    candidates = event_filter.filter_candidates(event, {"plant_id": "P1", "status": "RUNNING"})
    assert [c.monitor_id for c in candidates] == ["m_high_temp"]
