from datetime import datetime

from ontology.object_monitor.define.api.contracts import EvaluationRecord, EvaluationResult, ObjectChangeEvent
from ontology.object_monitor.define.compiler import build_monitor_artifact, parse_monitor_definition
from ontology.object_monitor.runtime import ActionGatewayResponse, ContextBuilder, L1Evaluator, ThinActionExecutor
from ontology.object_monitor.runtime.storage import InMemoryEvaluationLedger


class FlakyContextStore:
    def __init__(self, real_store):
        self._real_store = real_store
        self._failed = False

    def get(self, tenant_id: str, object_type: str, object_id: str):
        if not self._failed:
            self._failed = True
            raise RuntimeError("kv jitter")
        return self._real_store.get(tenant_id, object_type, object_id)


class ScriptedGateway:
    def __init__(self, responses):
        self._responses = list(responses)

    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _artifact(expr: str):
    payload = {
        "general": {"name": "m_fault", "description": "", "objectType": "Device", "enabled": True},
        "condition": {"objectSet": {"type": "Device", "properties": ["temperature", "status", "plant_id"]}, "rule": {"expression": expr}},
        "actions": [{"name": "create_ticket", "actionRef": "action://ticket/create", "parameters": {}}],
    }
    return build_monitor_artifact(parse_monitor_definition(payload), monitor_version=1)


def _event() -> ObjectChangeEvent:
    return ObjectChangeEvent(
        event_id="ev-1",
        tenant_id="t1",
        object_type="Device",
        object_id="D100",
        source_version=10,
        object_version=10,
        changed_fields=["temperature", "status"],
        event_time=datetime(2026, 1, 7, 10, 0, 0),
        trace_id="trace-1",
        change_source="outbox",
    )


def _evaluation() -> EvaluationRecord:
    return EvaluationRecord(
        evaluation_id="e1",
        tenant_id="t1",
        monitor_id="m_fault",
        monitor_version=1,
        object_id="D100",
        source_version=10,
        result=EvaluationResult.hit,
        reason="match",
        snapshot_hash="sha256:x",
        latency_ms=1,
        event_time=datetime(2026, 1, 7, 10, 0, 0),
    )


def test_w6_fault_drill_evaluator_handles_kv_jitter_and_recovers() -> None:
    builder = ContextBuilder()
    event = _event()
    builder.build(event, object_payload={"temperature": 70, "status": "RUNNING", "plant_id": "P1"})

    ledger = InMemoryEvaluationLedger()
    evaluator = L1Evaluator(FlakyContextStore(builder.store), ledger)
    artifact = _artifact("temperature >= 80 || status == 'RUNNING'")

    first = evaluator.evaluate_l1(event, [artifact])
    second = evaluator.evaluate_l1(event, [artifact])

    assert first == []
    assert len(second) == 1
    assert second[0].result is EvaluationResult.hit


def test_w6_fault_drill_expression_supports_or_and_in_list() -> None:
    builder = ContextBuilder()
    event = _event()
    builder.build(event, object_payload={"temperature": 70, "status": "IDLE", "plant_id": "P2"})

    ledger = InMemoryEvaluationLedger()
    evaluator = L1Evaluator(builder.store, ledger)
    artifact = _artifact("temperature >= 80 || plant_id in ['P1','P2']")

    rows = evaluator.evaluate_l1(event, [artifact])
    assert len(rows) == 1
    assert rows[0].result is EvaluationResult.hit


def test_w6_fault_drill_thin_executor_maps_timeout() -> None:
    gateway = ScriptedGateway([TimeoutError("timeout")])
    executor = ThinActionExecutor(gateway)

    result = executor.execute(
        _evaluation(),
        action_id="a1",
        endpoint="action://ticket/create",
        payload={"x": 1},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
    )

    assert result.success is False
    assert result.status_code == 599
    assert result.error_code == "timeout"
