import os
from datetime import datetime

import pytest

from neo4j import GraphDatabase

from ontology.action.storage.edits import AddObjectEdit, ModifyObjectEdit, ObjectLocator
from ontology.instance.storage.graph_store import Neo4jGraphStore
from ontology.object_monitor.define.api.contracts import ObjectChangeEvent
from ontology.object_monitor.define.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import ContextBuilder, EventFilter, L1Evaluator, MonitorRuntimeSpec, ThinActionExecutor
from ontology.object_monitor.runtime.thin_action_executor import ActionGatewayResponse
from ontology.object_monitor.runtime.capture.reconcile import InMemoryReconcileQueue
from ontology.object_monitor.runtime.storage.sqlite_repository import SqliteEvaluationLedger


class SuccessGateway:
    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        return ActionGatewayResponse(status_code=200, execution_id=f"exec-{action_id}")


def _artifact():
    payload = {
        "general": {"name": "m_neo4j_temp", "description": "", "objectType": "Device", "enabled": True},
        "condition": {"objectSet": {"type": "Device", "scope": "plant_id in ['P1']", "properties": ["temperature", "status", "plant_id"]}, "rule": {"expression": "temperature >= 80 && status == 'RUNNING'"}},
        "actions": [{"name": "create_ticket", "actionRef": "action://ticket/create", "parameters": {}}],
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def test_object_monitor_pipeline_with_neo4j() -> None:
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not password:
        pytest.skip("Neo4j credentials not configured")
    pytest.importorskip("neo4j")

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1").single()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Neo4j service unavailable in environment: {exc}")

    store = Neo4jGraphStore(uri=uri, user=user, password=password)
    with store._driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    store.apply_edit(AddObjectEdit("Device", "D100", {"temperature": 75, "status": "IDLE", "plant_id": "P1"}))
    store.apply_edit(ModifyObjectEdit(ObjectLocator("Device", "D100"), {"temperature": 86, "status": "RUNNING"}))
    updated = store.get_object(ObjectLocator("Device", "D100"))

    event = ObjectChangeEvent(
        event_id="ev-neo4j-1",
        tenant_id="t1",
        object_type="Device",
        object_id="D100",
        source_version=1001,
        object_version=updated.version or 0,
        changed_fields=["temperature", "status"],
        event_time=datetime(2026, 1, 10, 9, 0, 0),
        trace_id="trace-neo4j",
        change_source="neo4j_streams",
    )

    context_builder = ContextBuilder()
    context_builder.build(event, object_payload=updated.properties)

    artifact = _artifact()
    event_filter = EventFilter()
    event_filter.load_specs([MonitorRuntimeSpec(artifact=artifact, object_type="Device", watched_fields={"temperature", "status"})])
    context_payload = context_builder.store.get("t1", "Device", "D100").payload
    candidates = event_filter.filter_candidates(event, context_payload)
    assert len(candidates) == 1

    eval_ledger = SqliteEvaluationLedger(":memory:")
    reconcile = InMemoryReconcileQueue()
    evaluator = L1Evaluator(context_builder.store, eval_ledger, reconcile_queue=reconcile)
    evaluations = evaluator.evaluate_l1(event, candidates)

    assert len(evaluations) == 1
    assert evaluations[0].result.value == "HIT"
    assert reconcile.size() == 0

    executor = ThinActionExecutor(SuccessGateway())
    result = executor.execute(
        evaluations[0],
        action_id="ticket.create",
        endpoint="action://ticket/create",
        payload={"device": "D100"},
        idempotency_template=artifact.runtime_policy["idempotency_key_template"],
    )
    assert result.success is True
    assert result.execution_id == "exec-ticket.create"
