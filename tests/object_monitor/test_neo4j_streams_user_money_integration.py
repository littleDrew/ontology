import os
from datetime import datetime

import pytest
from neo4j import GraphDatabase

from ontology.action.storage.edits import AddObjectEdit, ModifyObjectEdit, ObjectLocator
from ontology.instance.storage.graph_store import Neo4jGraphStore
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import (
    ActionDispatcher,
    ActionGatewayResponse,
    ContextBuilder,
    EventFilter,
    L1Evaluator,
    MonitorRuntimeSpec,
    Neo4jStreamsEventMapper,
)
from ontology.object_monitor.runtime.reconcile import InMemoryReconcileQueue
from ontology.object_monitor.storage.sqlite_repository import SqliteActivityLedger, SqliteEvaluationLedger


class TagRichGateway:
    def __init__(self, graph_store: Neo4jGraphStore) -> None:
        self._graph_store = graph_store

    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        user_id = str(payload["user_id"])
        self._graph_store.apply_edit(
            ModifyObjectEdit(
                locator=ObjectLocator(object_type="User", primary_key=user_id),
                properties={"tag": "rich"},
            )
        )
        return ActionGatewayResponse(status_code=200, execution_id=f"exec-{action_id}")


def _artifact():
    payload = {
        "monitor": {"id": "m_user_money_rich", "objectType": "User", "scope": ""},
        "input": {"fields": ["money", "tag"]},
        "condition": {"expr": "money > 100"},
        "effect": {
            "action": {
                "endpoint": "action://user/tag-rich",
                "idempotencyKey": "${monitorId}:${objectId}:${sourceVersion}:${actionId}",
            }
        },
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def test_streams_money_update_triggers_action_and_updates_tag() -> None:
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not password:
        raise RuntimeError("Neo4j credentials not configured: set NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD")

    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        with driver.session() as session:
            session.run("RETURN 1").single()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Neo4j service unavailable in environment: {exc}") from exc

    store = Neo4jGraphStore(uri=uri, user=user, password=password)
    with store._driver.session() as session:
        session.run("MATCH (n:User) DETACH DELETE n")

    store.apply_edit(AddObjectEdit("User", "U100", {"money": 50, "tag": "poor"}))
    before = store.get_object(ObjectLocator("User", "U100"))

    store.apply_edit(ModifyObjectEdit(ObjectLocator("User", "U100"), {"money": 150}))
    after = store.get_object(ObjectLocator("User", "U100"))

    stream_message = {
        "meta": {
            "txId": after.version or 0,
            "txSeq": after.version or 0,
            "timestamp": datetime.utcnow().isoformat(),
        },
        "payload": {
            "before": {"properties": {"primary_key": "U100", **before.properties}},
            "after": {"properties": {"primary_key": "U100", **after.properties}},
        },
    }
    event = Neo4jStreamsEventMapper.from_streams_message(
        stream_message,
        tenant_id="t1",
        object_type="User",
        object_id_field="primary_key",
    )

    context_builder = ContextBuilder()
    context_builder.build(event, object_payload=after.properties)

    artifact = _artifact()
    event_filter = EventFilter()
    event_filter.load_specs([MonitorRuntimeSpec(artifact=artifact, object_type="User", watched_fields={"money"})])
    context_payload = context_builder.store.get("t1", "User", "U100").payload
    candidates = event_filter.filter_candidates(event, context_payload)
    assert len(candidates) == 1

    eval_ledger = SqliteEvaluationLedger(":memory:")
    reconcile = InMemoryReconcileQueue()
    evaluator = L1Evaluator(context_builder.store, eval_ledger, reconcile_queue=reconcile)
    evaluations = evaluator.evaluate_l1(event, candidates)

    assert len(evaluations) == 1
    assert evaluations[0].result.value == "HIT"

    activity_ledger = SqliteActivityLedger(":memory:")
    dispatcher = ActionDispatcher(TagRichGateway(store), activity_ledger)
    activity_id = dispatcher.dispatch(
        evaluations[0],
        action_id="user.tag.rich",
        endpoint="action://user/tag-rich",
        payload={"user_id": "U100"},
        idempotency_template=artifact.action_template["idempotency_key"],
    )

    activity = activity_ledger.get_activity(activity_id)
    assert activity.status == "succeeded"

    final_obj = store.get_object(ObjectLocator("User", "U100"))
    assert final_obj.properties["money"] == 150
    assert final_obj.properties["tag"] == "rich"
