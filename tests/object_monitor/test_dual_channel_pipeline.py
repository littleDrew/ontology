from datetime import datetime

from ontology.object_monitor.api.contracts import PropertyChange
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import (
    ChangeNormalizer,
    ContextBuilder,
    EventFilter,
    L1Evaluator,
    MonitorRuntimeSpec,
    Neo4jCdcMapper,
    SingleChannelIngestionPipeline,
)
from ontology.object_monitor.storage import SqlAlchemyEvaluationLedger


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


def test_single_channel_stream_event_dedupe_and_e2e_runtime() -> None:
    now = datetime(2026, 2, 2, 9, 0, 0)
    payload = {
        "txId": "ev-stream-1",
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
        "traceId": "tr-stream",
    }
    stream_event = Neo4jCdcMapper.from_cdc_payload(payload)

    pipeline = SingleChannelIngestionPipeline(ChangeNormalizer(dedupe_window_seconds=60))
    result = pipeline.ingest([stream_event, stream_event])
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
