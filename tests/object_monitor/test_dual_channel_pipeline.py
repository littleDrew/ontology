from datetime import datetime

from ontology.object_monitor.define.api.contracts import PropertyChange
from ontology.object_monitor.define.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import (
    ChangeNormalizer,
    ContextBuilder,
    EventFilter,
    L1Evaluator,
    MonitorRuntimeSpec,
    SingleChannelIngestionPipeline,
)
from ontology.object_monitor.runtime.storage import SqlAlchemyEvaluationLedger


def _artifact():
    payload = {
        "general": {"name": "m_pipe", "description": "", "objectType": "Device", "enabled": True},
        "condition": {"objectSet": {"type": "Device", "scope": "plant_id in ['P1']", "properties": ["temperature", "status", "plant_id"]}, "rule": {"expression": "temperature >= 80 && status == 'RUNNING'"}},
        "actions": [{"name": "create_ticket", "actionRef": "action://ticket/create", "parameters": {}}],
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
    from ontology.object_monitor.define.api.contracts import ObjectChangeEvent

    stream_event = ObjectChangeEvent(
        event_id=str(payload["txId"]),
        tenant_id=str(payload["tenantId"]),
        object_type=str(payload["label"]),
        object_id=str(payload["primaryKey"]),
        source_version=int(payload["sourceVersion"]),
        object_version=int(payload["objectVersion"]),
        changed_fields=["temperature", "status"],
        event_time=now,
        trace_id=str(payload["traceId"]),
        change_source="neo4j_streams",
        changed_properties=[
            PropertyChange(field="status", old_value="IDLE", new_value="RUNNING"),
            PropertyChange(field="temperature", old_value=75, new_value=86),
        ],
    )

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

