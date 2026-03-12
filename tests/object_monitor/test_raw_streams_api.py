from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import types

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from ontology.object_monitor.runtime.api.data_plane_app import ObjectMonitorDataPlaneService, create_object_monitor_data_plane_app
from ontology.object_monitor.runtime.action_dispatcher import ActionDispatcher, ActionGatewayResponse
from ontology.object_monitor.runtime.capture.normalizer import ChangeNormalizer
from ontology.object_monitor.runtime.capture.pipeline import SingleChannelIngestionPipeline
from ontology.object_monitor.runtime.capture.raw_consumer import KafkaConsumerConfig, KafkaRawConsumerRunner, RawConsumerRuntime, RawTopicMessage
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


def _relation_streams_event() -> dict:
    return {
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
            "before": {"properties": {"salary": 18000, "start_date": "2024-01-01", "status": "active"}},
            "after": {"properties": {"salary": 20000, "start_date": "2024-01-01", "status": "active"}},
            "label": "WORKS_AS",
            "type": "relationship",
        },
        "schema": {"properties": {"salary": "Long", "start_date": "String", "status": "String"}, "Constraints": []},
    }


class FakeKafkaConsumer:
    last_init_kwargs: dict | None = None
    seeded_records: dict[object, list[object]] = {}

    def __init__(self, *topics: str, **kwargs) -> None:
        self._topics = topics
        self._kwargs = kwargs
        FakeKafkaConsumer.last_init_kwargs = {"topics": topics, **kwargs}

    def poll(self, timeout_ms: int = 1000) -> dict[object, list[object]]:
        _ = timeout_ms
        out = FakeKafkaConsumer.seeded_records
        FakeKafkaConsumer.seeded_records = {}
        return out

    def close(self) -> None:
        return None


def test_streams_kafka_consumer_end_to_end_to_data_plane(monkeypatch: pytest.MonkeyPatch) -> None:
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
        raw_consumer=None,
        kafka_runner=None,
    )
    monitor_service.raw_consumer = RawConsumerRuntime(
        pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60)),
        event_handler=lambda event: monitor_service.process_event(event),
    )
    topic_partition = "tp0"
    message = SimpleNamespace(key=None, value=_relation_streams_event(), partition=0, offset=7)
    data_plane_client = TestClient(create_object_monitor_data_plane_app(monitor_service))
    FakeKafkaConsumer.seeded_records = {topic_partition: [message]}
    fake_kafka_module = types.SimpleNamespace(KafkaConsumer=FakeKafkaConsumer)
    monkeypatch.setitem(__import__("sys").modules, "kafka", fake_kafka_module)
    monitor_service.kafka_runner = KafkaRawConsumerRunner(
        runtime=monitor_service.raw_consumer,
        config=KafkaConsumerConfig(bootstrap_servers="fake:9092", group_id="object-monitor-runtime"),
    )
    reload_resp = data_plane_client.post("/api/v1/data-plane/reload-artifacts", json={"artifacts": artifacts.json()})
    assert reload_resp.status_code == 200

    poll = data_plane_client.post("/api/v1/data-plane/raw/consumer/poll-once")
    assert poll.status_code == 200
    assert poll.json()["consumed"] == 1
    assert FakeKafkaConsumer.last_init_kwargs is not None
    assert FakeKafkaConsumer.last_init_kwargs["topics"] == ("object_change_raw",)
    assert FakeKafkaConsumer.last_init_kwargs["bootstrap_servers"] == "fake:9092"

    activities = data_plane_client.get("/api/v1/data-plane/activities", params={"tenant_id": "global"})
    assert activities.status_code == 200
    assert len(activities.json()) == 1
    assert activities.json()[0]["status"] == "succeeded"


def test_raw_consumer_metrics_endpoint_reports_kafka_runner_state() -> None:
    service = ObjectMonitorDataPlaneService(
        context_builder=ContextBuilder(),
        event_filter=EventFilter(),
        evaluator=L1Evaluator(ContextBuilder().store, InMemoryEvaluationLedger()),
        dispatcher=ActionDispatcher(LocalActionGateway(TestClient(build_ontology_main_server_app())), InMemoryActivityLedger()),
        evaluation_ledger=InMemoryEvaluationLedger(),
        activity_ledger=InMemoryActivityLedger(),
        raw_consumer=RawConsumerRuntime(
            pipeline=SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60)),
            event_handler=lambda _: None,
        ),
        kafka_runner=None,
    )
    client = TestClient(create_object_monitor_data_plane_app(service))
    response = client.get("/api/v1/data-plane/raw/metrics")
    assert response.status_code == 200
    assert response.json()["kafka_consumer_running"] is False
    assert response.json()["enabled"] is True

    canonical_event = {
        "event_id": "evt-1",
        "tenant_id": "default",
        "object_type": "User",
        "object_id": "U1",
        "source_version": 1,
        "object_version": 1,
        "changed_fields": ["money"],
        "event_time": datetime.now(timezone.utc).isoformat(),
        "trace_id": "trace-1",
        "changed_properties": [{"field": "money", "old_value": 1, "new_value": 2}],
    }
    service.raw_consumer.consume_message(
        # 直接模拟 Kafka 消息进入 runtime，而非通过 REST 注入
        RawTopicMessage(topic="object_change_raw", value=canonical_event, key=None, partition=0, offset=0)
    )
    metrics = client.get("/api/v1/data-plane/raw/metrics").json()["metrics"]
    assert metrics["consumed"] == 1
