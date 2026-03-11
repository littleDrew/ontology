from datetime import datetime

from ontology.object_monitor.api.contracts import EvaluationResult, ObjectChangeEvent
from ontology.object_monitor.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import ContextBuilder, L1Evaluator
from ontology.object_monitor.storage import EvaluationQuery, InMemoryEvaluationLedger


def _artifact(monitor_id: str, expr: str):
    payload = {
        "general": {"name": monitor_id, "description": "", "objectType": "Device", "enabled": True},
        "condition": {"objectSet": {"type": "Device", "properties": ["temperature", "status", "owner_name"]}, "rule": {"expression": expr}},
        "actions": [{"name": "create_ticket", "actionRef": "action://ticket/create", "parameters": {}}],
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def _event(source_version: int = 900) -> ObjectChangeEvent:
    return ObjectChangeEvent(
        event_id="evt-1",
        tenant_id="t1",
        object_type="Device",
        object_id="D100",
        source_version=source_version,
        object_version=21,
        changed_fields=["temperature", "status"],
        event_time=datetime(2026, 1, 4, 12, 0, 0),
        trace_id="trace-1",
        change_source="outbox",
    )


def test_w4_l1_evaluator_writes_hit_and_miss_records() -> None:
    ledger = InMemoryEvaluationLedger()
    builder = ContextBuilder()
    event = _event()
    builder.build(
        event,
        object_payload={"temperature": 85, "status": "RUNNING", "owner_name": "alice"},
    )

    evaluator = L1Evaluator(builder.store, ledger)
    artifacts = [
        _artifact("m_hit", "temperature >= 80 && status == 'RUNNING'"),
        _artifact("m_miss", "temperature >= 90 && status == 'RUNNING'"),
    ]

    records = evaluator.evaluate_l1(event, artifacts)
    assert len(records) == 2
    by_monitor = {row.monitor_id: row for row in records}
    assert by_monitor["m_hit"].result is EvaluationResult.hit
    assert by_monitor["m_miss"].result is EvaluationResult.miss

    queried = ledger.query(EvaluationQuery(tenant_id="t1", object_id="D100"))
    assert len(queried) == 2


def test_w4_evaluator_idempotent_write_on_reconsume() -> None:
    ledger = InMemoryEvaluationLedger()
    builder = ContextBuilder()
    event = _event(source_version=901)
    builder.build(event, object_payload={"temperature": 70, "status": "RUNNING"})

    evaluator = L1Evaluator(builder.store, ledger)
    artifact = _artifact("m_once", "temperature >= 60 && status == 'RUNNING'")

    first = evaluator.evaluate_l1(event, [artifact])
    second = evaluator.evaluate_l1(event, [artifact])
    assert len(first) == 1
    assert second == []

    queried = ledger.query(EvaluationQuery(tenant_id="t1", monitor_id="m_once"))
    assert len(queried) == 1
    assert queried[0].source_version == 901


def test_w4_ledger_query_by_time_range() -> None:
    ledger = InMemoryEvaluationLedger()
    builder = ContextBuilder()
    base = datetime(2026, 1, 5, 10, 0, 0)

    e1 = ObjectChangeEvent(
        event_id="e1",
        tenant_id="t1",
        object_type="Device",
        object_id="D200",
        source_version=1,
        object_version=1,
        changed_fields=["temperature"],
        event_time=base,
        trace_id="t1",
        change_source="outbox",
    )
    e2 = ObjectChangeEvent(
        event_id="e2",
        tenant_id="t1",
        object_type="Device",
        object_id="D200",
        source_version=2,
        object_version=2,
        changed_fields=["temperature"],
        event_time=base.replace(hour=11),
        trace_id="t2",
        change_source="outbox",
    )

    evaluator = L1Evaluator(builder.store, ledger)
    art = _artifact("m_temp", "temperature >= 0")
    builder.build(e1, object_payload={"temperature": 1, "status": "RUNNING"})
    evaluator.evaluate_l1(e1, [art])
    builder.build(e2, object_payload={"temperature": 2, "status": "RUNNING"})
    evaluator.evaluate_l1(e2, [art])

    rows = ledger.query(EvaluationQuery(tenant_id="t1", start_time=base.replace(hour=11), end_time=base.replace(hour=11)))
    assert len(rows) == 1
    assert rows[0].source_version == 2
