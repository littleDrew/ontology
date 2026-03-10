from datetime import datetime

from ontology.object_monitor.api.contracts import ObjectChangeEvent, PropertyChange
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import ContextBuilder, DualChannelIngestionPipeline, EventFilter, L1Evaluator, MonitorRuntimeSpec, Neo4jCdcMapper
from ontology.object_monitor.runtime.action_dispatcher import ActionDispatcher, ActionGatewayResponse
from ontology.object_monitor.runtime.normalizer import ChangeNormalizer
from ontology.object_monitor.storage import SqlAlchemyActivityLedger, SqlAlchemyChangeOutboxRepository, SqlAlchemyEvaluationLedger


class SuccessGateway:
    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        return ActionGatewayResponse(status_code=200, execution_id=f"exec-{action_id}")


def _artifact():
    payload = {
        "monitor": {"id": "m_pipe", "objectType": "Device", "scope": "plant_id in ['P1']"},
        "input": {"fields": ["temperature", "status", "plant_id"]},
        "condition": {"expr": "temperature >= 80 && status == 'RUNNING'"},
        "effect": {
            "action": {
                "endpoint": "action://ticket/create",
                "idempotencyKey": "${monitorId}:${objectId}:${sourceVersion}:${actionId}",
            }
        },
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def test_dual_channel_outbox_plus_cdc_dedupe_and_e2e_runtime() -> None:
    outbox = SqlAlchemyChangeOutboxRepository("sqlite:///:memory:")
    now = datetime(2026, 2, 2, 9, 0, 0)
    outbox_event = ObjectChangeEvent(
        event_id="ev-out-1",
        tenant_id="t1",
        object_type="Device",
        object_id="D1",
        source_version=100,
        object_version=7,
        changed_fields=["temperature", "status"],
        event_time=now,
        trace_id="tr-out",
        change_source="outbox",
    )
    outbox.add(outbox_event, source="outbox")

    cdc_payload = {
        "txId": "ev-cdc-1",
        "tenantId": "t1",
        "label": "Device",
        "primaryKey": "D1",
        "sourceVersion": 100,
        "objectVersion": 7,
        "changedProperties": [
            {"field": "temperature", "old": 75, "new": 86},
            {"field": "status", "old": "IDLE", "new": "RUNNING"},
        ],
        "eventTime": now.isoformat(),
        "traceId": "tr-cdc",
    }
    cdc_event = Neo4jCdcMapper.from_cdc_payload(cdc_payload)

    pipeline = DualChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60))
    result = pipeline.ingest(outbox.claim_pending(limit=10), [cdc_event])
    assert len(result.normalized_events) == 1
    assert result.deduped_count == 1

    event = result.normalized_events[0]
    assert event.changed_properties == [
        PropertyChange(field="status", old_value="IDLE", new_value="RUNNING"),
        PropertyChange(field="temperature", old_value=75, new_value=86),
    ]
    builder = ContextBuilder()
    builder.build(event, object_payload={"temperature": 86, "status": "RUNNING", "plant_id": "P1"})

    artifact = _artifact()
    event_filter = EventFilter()
    event_filter.load_specs([MonitorRuntimeSpec(artifact=artifact, object_type="Device", watched_fields={"temperature", "status"})])
    candidates = event_filter.filter_candidates(event, builder.store.get("t1", "Device", "D1").payload)

    eval_ledger = SqlAlchemyEvaluationLedger("sqlite:///:memory:")
    evaluator = L1Evaluator(builder.store, eval_ledger)
    evaluations = evaluator.evaluate_l1(event, candidates)
    assert len(evaluations) == 1
    assert evaluations[0].result.value == "HIT"

    activity_ledger = SqlAlchemyActivityLedger("sqlite:///:memory:")
    dispatcher = ActionDispatcher(SuccessGateway(), activity_ledger)
    activity_id = dispatcher.dispatch(
        evaluations[0],
        action_id="ticket.create",
        endpoint="action://ticket/create",
        payload={"device": "D1"},
        idempotency_template=artifact.action_template["idempotency_key"],
    )
    assert activity_ledger.get_activity(activity_id).status == "succeeded"


def test_neo4j_cdc_mapper_supports_before_after_payload() -> None:
    payload = {
        "txId": "ev-cdc-2",
        "tenantId": "t1",
        "label": "Device",
        "primaryKey": "D2",
        "sourceVersion": 101,
        "objectVersion": 8,
        "eventTime": datetime(2026, 2, 2, 9, 1, 0).isoformat(),
        "before": {"temperature": 70, "status": "IDLE"},
        "after": {"temperature": 71, "status": "RUNNING"},
    }
    event = Neo4jCdcMapper.from_cdc_payload(payload)
    assert event.changed_fields == ["status", "temperature"]
    assert event.changed_properties == [
        PropertyChange(field="status", old_value="IDLE", new_value="RUNNING"),
        PropertyChange(field="temperature", old_value=70, new_value=71),
    ]


def test_dual_channel_pipeline_merges_deduped_property_changes_from_both_channels() -> None:
    now = datetime(2026, 2, 2, 9, 10, 0)
    outbox_event = ObjectChangeEvent(
        event_id="ev-out-merge",
        tenant_id="t1",
        object_type="Device",
        object_id="D3",
        source_version=110,
        object_version=9,
        changed_fields=["temperature"],
        event_time=now,
        trace_id="tr-out-merge",
        change_source="outbox",
        changed_properties=[PropertyChange(field="temperature", old_value=70, new_value=85)],
    )
    cdc_event = ObjectChangeEvent(
        event_id="ev-cdc-merge",
        tenant_id="t1",
        object_type="Device",
        object_id="D3",
        source_version=110,
        object_version=9,
        changed_fields=["status"],
        event_time=now,
        trace_id="tr-cdc-merge",
        change_source="neo4j_cdc",
        changed_properties=[PropertyChange(field="status", old_value="IDLE", new_value="RUNNING")],
    )

    pipeline = DualChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60))
    result = pipeline.ingest([outbox_event], [cdc_event])

    assert len(result.normalized_events) == 1
    assert result.deduped_count == 1
    assert result.normalized_events[0].changed_fields == ["status", "temperature"]
    assert result.normalized_events[0].changed_properties == [
        PropertyChange(field="status", old_value="IDLE", new_value="RUNNING"),
        PropertyChange(field="temperature", old_value=70, new_value=85),
    ]
