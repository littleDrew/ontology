from __future__ import annotations

from datetime import datetime, timezone

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from ontology.object_monitor.runtime.api.change_capture_app import ChangeCaptureService, create_change_capture_app
from ontology.object_monitor.runtime.api.data_plane_app import ObjectMonitorDataPlaneService, create_object_monitor_data_plane_app
from ontology.object_monitor.runtime.action_dispatcher import ActionDispatcher, ActionGatewayResponse
from ontology.object_monitor.runtime.context_builder import ContextBuilder
from ontology.object_monitor.runtime.event_filter import EventFilter
from ontology.object_monitor.runtime.evaluator import L1Evaluator
from ontology.object_monitor.runtime.storage.activity_repository import InMemoryActivityLedger
from ontology.object_monitor.runtime.storage.repository import InMemoryEvaluationLedger
from ontology.service_factory import build_ontology_main_server_app


class LocalActionGateway:
    def __init__(self, client: TestClient) -> None:
        self._client = client

    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        response = self._client.post(
            f"/api/v1/actions/{action_id}/apply",
            json={"submitter": "monitor", "input_payload": payload, "client_request_id": idempotency_key},
        )
        if response.status_code < 300:
            return ActionGatewayResponse(status_code=response.status_code, execution_id=response.json().get("execution_id"))
        return ActionGatewayResponse(status_code=response.status_code, error_message=str(response.json()))


RELATION_STREAMS_EVENT = {
    "meta": {
        "timestamp": 1773211152391,
        "username": "neo4j",
        "txId": 263,
        "txEventId": 0,
        "txEventsCount": 1,
        "operation": "updated",
        "source": {"hostname": "neo4j"},
    },
    "payload": {
        "id": "506",
        "start": {"id": "421", "labels": ["Person"], "ids": {}},
        "end": {"id": "422", "labels": ["Job"], "ids": {}},
        "before": {
            "properties": {
                "salary": 18000,
                "start_date": "2024-01-01",
                "status": "active",
            }
        },
        "after": {
            "properties": {
                "salary": 20000,
                "start_date": "2024-01-01",
                "status": "active",
            }
        },
        "label": "WORKS_AS",
        "type": "relationship",
    },
    "schema": {"properties": {"salary": "Long", "start_date": "String", "status": "String"}, "Constraints": []},
}


def test_change_capture_normalizes_relationship_streams_event() -> None:
    app = create_change_capture_app(ChangeCaptureService(data_plane_base_url=None))
    client = TestClient(app)

    response = client.post("/api/v1/change-capture/neo4j/streams", json={"payload": RELATION_STREAMS_EVENT})
    assert response.status_code == 200
    body = response.json()["event"]

    assert body["tenant_id"] == "global"
    assert body["object_type"] == "WORKS_AS"
    assert body["object_id"] == "506"
    assert body["changed_fields"] == ["salary"]
    assert body["changed_properties"] == [{"field": "salary", "old_value": 18000, "new_value": 20000}]


def test_change_capture_normalizes_node_streams_event() -> None:
    app = create_change_capture_app(ChangeCaptureService(data_plane_base_url=None))
    client = TestClient(app)
    event = {
        "meta": {"timestamp": 1773195063404, "txId": 197},
        "payload": {
            "id": "12",
            "before": {"properties": {"city": "北京"}, "labels": ["Person"]},
            "after": {"properties": {"city": "上海"}, "labels": ["Person"]},
            "type": "node",
        },
    }

    response = client.post("/api/v1/change-capture/neo4j/streams", json={"payload": event})
    assert response.status_code == 200
    body = response.json()["event"]

    assert body["tenant_id"] == "global"
    assert body["object_type"] == "Person"
    assert body["object_id"] == "12"
    assert body["changed_fields"] == ["city"]


def test_relationship_streams_event_end_to_end_to_data_plane() -> None:
    main_client = TestClient(build_ontology_main_server_app())
    create_action = main_client.post(
        "/api/v1/actions",
        json={"action_id": "works_as-raise", "description": "mark raise", "function_name": "noop_action", "version": 1},
    )
    assert create_action.status_code == 200

    monitor_payload = {
        "general": {"name": "works_as_raise_monitor", "description": "demo", "objectType": "WORKS_AS", "enabled": True},
        "condition": {
            "objectSet": {"type": "WORKS_AS", "properties": ["salary", "status"]},
            "rule": {"expression": "salary >= 20000"},
        },
        "actions": [{"name": "tag_raise", "actionRef": "action://works/as-raise", "parameters": {"tag": "raised"}}],
    }

    created_monitor = main_client.post(
        "/api/v1/monitors",
        json={"payload": monitor_payload, "available_fields": ["salary", "status"], "operator": "alice"},
    )
    assert created_monitor.status_code == 200
    version = created_monitor.json()["monitor_version"]
    publish = main_client.post(f"/api/v1/monitors/works_as_raise_monitor/versions/{version}/publish", json={"operator": "alice"})
    assert publish.status_code == 200
    artifacts = main_client.get("/api/v1/monitors/active-artifacts")
    assert artifacts.status_code == 200

    context_builder = ContextBuilder()
    event_filter = EventFilter()
    eval_ledger = InMemoryEvaluationLedger()
    activity_ledger = InMemoryActivityLedger()
    evaluator = L1Evaluator(context_builder.store, eval_ledger)
    dispatcher = ActionDispatcher(LocalActionGateway(main_client), activity_ledger)
    monitor_service = ObjectMonitorDataPlaneService(
        context_builder=context_builder,
        event_filter=event_filter,
        evaluator=evaluator,
        dispatcher=dispatcher,
        evaluation_ledger=eval_ledger,
        activity_ledger=activity_ledger,
    )
    data_plane_client = TestClient(create_object_monitor_data_plane_app(monitor_service))
    reload_resp = data_plane_client.post("/api/v1/data-plane/reload-artifacts", json={"artifacts": artifacts.json()})
    assert reload_resp.status_code == 200

    capture_client = TestClient(create_change_capture_app(ChangeCaptureService(data_plane_base_url=None)))
    normalized = capture_client.post("/api/v1/change-capture/neo4j/streams", json={"payload": RELATION_STREAMS_EVENT})
    assert normalized.status_code == 200

    ingest = data_plane_client.post("/api/v1/data-plane/events/object-change", json=normalized.json()["event"])
    assert ingest.status_code == 200
    assert ingest.json()["evaluation_count"] == 1
    assert len(ingest.json()["activity_ids"]) == 1

    activities = data_plane_client.get("/api/v1/data-plane/activities", params={"tenant_id": "global"})
    assert activities.status_code == 200
    assert activities.json()[0]["status"] == "succeeded"
