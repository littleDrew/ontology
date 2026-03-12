from __future__ import annotations

from types import SimpleNamespace

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from ontology.object_monitor.runtime.api.data_plane_app import ObjectMonitorDataPlaneService, create_object_monitor_data_plane_app
from ontology.object_monitor.runtime.action_dispatcher import ActionDispatcher, ActionGatewayResponse
from ontology.object_monitor.runtime.capture.normalizer import ChangeNormalizer
from ontology.object_monitor.runtime.capture.pipeline import SingleChannelIngestionPipeline
from ontology.object_monitor.runtime.capture.raw_consumer import KafkaConsumerConfig, KafkaRawConsumerRunner, RawConsumerRuntime
from ontology.object_monitor.runtime.context_builder import ContextBuilder
from ontology.object_monitor.runtime.event_filter import EventFilter
from ontology.object_monitor.runtime.evaluator import L1Evaluator
from ontology.object_monitor.runtime.storage.activity_repository import InMemoryActivityLedger
from ontology.object_monitor.runtime.storage.repository import InMemoryEvaluationLedger
from scripts.object_monitor.service_factory import build_ontology_main_server_app


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


class FakeConsumer:
    def __init__(self, records: dict[object, list[object]]) -> None:
        self._records = records

    def poll(self, timeout_ms: int = 1000) -> dict[object, list[object]]:
        _ = timeout_ms
        out = self._records
        self._records = {}
        return out

    def close(self) -> None:
        return None


def _monitor_payload() -> dict:
    return {
        "general": {"name": "user_rich_monitor", "description": "demo", "objectType": "User", "enabled": True},
        "condition": {
            "objectSet": {"type": "User", "properties": ["money", "tag"]},
            "rule": {"expression": "money > 100"},
        },
        "actions": [{"name": "set_tag", "actionRef": "action://user/set-label", "parameters": {"label": "rich"}}],
    }


def test_multi_service_rest_e2e() -> None:
    main_client = TestClient(build_ontology_main_server_app())

    create_action = main_client.post(
        "/api/v1/actions",
        json={"action_id": "user_set-label", "description": "set label", "function_name": "noop_action", "version": 1},
    )
    assert create_action.status_code == 200

    created_monitor = main_client.post(
        "/api/v1/monitors",
        json={"payload": _monitor_payload(), "available_fields": ["money", "tag"], "operator": "alice"},
    )
    assert created_monitor.status_code == 200
    version = created_monitor.json()["monitor_version"]

    published = main_client.post(f"/api/v1/monitors/user_rich_monitor/versions/{version}/publish", json={"operator": "alice"})
    assert published.status_code == 200

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
        raw_consumer=None,
        kafka_runner=None,
    )
    monitor_service.raw_consumer = RawConsumerRuntime(
        pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60)),
        event_handler=lambda event: monitor_service.process_event(event),
    )
    msg = SimpleNamespace(
        key=None,
        partition=0,
        offset=1,
        value={
            "event_id": "evt-1",
            "tenant_id": "default",
            "object_type": "User",
            "object_id": "U100",
            "source_version": 1,
            "object_version": 1,
            "changed_fields": ["money"],
            "event_time": "2026-01-01T00:00:00+00:00",
            "trace_id": "tx-1",
            "change_source": "outbox",
            "changed_properties": [{"field": "money", "old_value": 50, "new_value": 150}],
        },
    )
    monitor_service.kafka_runner = KafkaRawConsumerRunner(
        runtime=monitor_service.raw_consumer,
        config=KafkaConsumerConfig(bootstrap_servers="fake:9092"),
        consumer_factory=lambda _: FakeConsumer({"tp0": [msg]}),
    )

    data_plane_client = TestClient(create_object_monitor_data_plane_app(monitor_service))

    reload_resp = data_plane_client.post("/api/v1/data-plane/reload-artifacts", json={"artifacts": artifacts.json()})
    assert reload_resp.status_code == 200
    assert reload_resp.json()["loaded"] == 1

    poll = data_plane_client.post("/api/v1/data-plane/raw/consumer/poll-once")
    assert poll.status_code == 200
    assert poll.json()["consumed"] == 1

    activities = data_plane_client.get("/api/v1/data-plane/activities", params={"tenant_id": "default"})
    assert activities.status_code == 200
    assert activities.json()[0]["status"] == "succeeded"
