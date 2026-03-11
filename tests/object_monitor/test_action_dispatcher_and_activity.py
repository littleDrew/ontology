from datetime import datetime

from ontology.object_monitor.define.api.contracts import EvaluationRecord, EvaluationResult
from ontology.object_monitor.runtime import ActionGatewayResponse, ThinActionExecutor


class ScriptedGateway:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> ActionGatewayResponse:
        self.calls.append(
            {
                "action_id": action_id,
                "endpoint": endpoint,
                "payload": payload,
                "idempotency_key": idempotency_key,
            }
        )
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _evaluation() -> EvaluationRecord:
    return EvaluationRecord(
        evaluation_id="ev-1",
        tenant_id="t1",
        monitor_id="m_hot",
        monitor_version=3,
        object_id="D100",
        source_version=99,
        result=EvaluationResult.hit,
        reason="matched",
        snapshot_hash="sha256:abc",
        latency_ms=12,
        event_time=datetime(2026, 1, 6, 9, 0, 0),
    )


def test_thin_executor_success() -> None:
    gateway = ScriptedGateway([ActionGatewayResponse(status_code=200, execution_id="exec-1")])
    executor = ThinActionExecutor(gateway)

    result = executor.execute(
        _evaluation(),
        action_id="a_ticket",
        endpoint="action://ticket/create",
        payload={"severity": "high"},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
    )

    assert result.success is True
    assert result.execution_id == "exec-1"
    assert gateway.calls[0]["idempotency_key"] == "m_hot:D100:99:a_ticket"


def test_thin_executor_non_retryable_failure() -> None:
    gateway = ScriptedGateway([ActionGatewayResponse(status_code=422, error_code="invalid_payload", error_message="bad")])
    executor = ThinActionExecutor(gateway)

    result = executor.execute(
        _evaluation(),
        action_id="a_ticket",
        endpoint="action://ticket/create",
        payload={"severity": "bad"},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
    )

    assert result.success is False
    assert result.status_code == 422
    assert result.error_code == "invalid_payload"


def test_thin_executor_timeout_maps_to_599() -> None:
    gateway = ScriptedGateway([TimeoutError("timeout")])
    executor = ThinActionExecutor(gateway)

    result = executor.execute(
        _evaluation(),
        action_id="a_ticket",
        endpoint="action://ticket/create",
        payload={"severity": "high"},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
    )

    assert result.success is False
    assert result.status_code == 599
    assert result.error_code == "timeout"
