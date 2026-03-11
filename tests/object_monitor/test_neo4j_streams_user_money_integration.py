from datetime import UTC, datetime


from ontology.action.storage.edits import AddObjectEdit, ModifyObjectEdit, ObjectLocator
from ontology.instance.storage.graph_store import Neo4jGraphStore
from ontology.object_monitor.define.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import (
    ActionGatewayResponse,
    ContextBuilder,
    EventFilter,
    L1Evaluator,
    MonitorRuntimeSpec,
    Neo4jStreamsEventMapper,
    ThinActionExecutor,
)
from ontology.object_monitor.runtime.capture.reconcile import InMemoryReconcileQueue
from ontology.object_monitor.runtime.storage.sqlite_repository import SqliteEvaluationLedger
from tests.object_monitor._neo4j_test_runtime import runtime_neo4j_credentials


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
        "general": {"name": "m_user_money_rich", "description": "", "objectType": "User", "enabled": True},
        "condition": {"objectSet": {"type": "User", "properties": ["money", "tag"]}, "rule": {"expression": "money > 100"}},
        "actions": [{"name": "tag_rich", "actionRef": "action://user/tag-rich", "parameters": {"tag": "rich"}}],
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def test_streams_money_update_triggers_action_and_updates_tag() -> None:
    with runtime_neo4j_credentials() as (uri, user, password):
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
                "timestamp": datetime.now(UTC).isoformat(),
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

        executor = ThinActionExecutor(TagRichGateway(store))
        result = executor.execute(
            evaluations[0],
            action_id="user.tag.rich",
            endpoint="action://user/tag-rich",
            payload={"user_id": "U100"},
            idempotency_template=artifact.runtime_policy["idempotency_key_template"],
        )
        assert result.success is True

        final_obj = store.get_object(ObjectLocator("User", "U100"))
        assert final_obj.properties["money"] == 150
        assert final_obj.properties["tag"] == "rich"
        store._driver.close()
