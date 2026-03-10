from datetime import datetime, timedelta

from ontology.object_monitor.api.contracts import EvaluationRecord, EvaluationResult
from ontology.object_monitor.runtime import ActionDispatcher, ActionGatewayResponse
from ontology.object_monitor.storage import InMemoryActivityLedger


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


def test_w5_dispatch_success_updates_activity_and_delivery_log() -> None:
    gateway = ScriptedGateway([ActionGatewayResponse(status_code=200, execution_id="exec-1")])
    ledger = InMemoryActivityLedger()
    dispatcher = ActionDispatcher(gateway, ledger)

    activity_id = dispatcher.dispatch(
        _evaluation(),
        action_id="a_ticket",
        endpoint="action://ticket/create",
        payload={"severity": "high"},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
        now=datetime(2026, 1, 6, 9, 0, 1),
    )

    activity = ledger.get_activity(activity_id)
    logs = ledger.get_delivery_logs(activity_id)
    assert activity.status == "succeeded"
    assert activity.action_execution_id == "exec-1"
    assert len(logs) == 1
    assert logs[0].status == "succeeded"
    assert gateway.calls[0]["idempotency_key"] == "m_hot:D100:99:a_ticket"


def test_w5_dispatch_4xx_fails_without_retry() -> None:
    gateway = ScriptedGateway([ActionGatewayResponse(status_code=422, error_code="invalid_payload", error_message="bad")])
    ledger = InMemoryActivityLedger()
    dispatcher = ActionDispatcher(gateway, ledger)

    activity_id = dispatcher.dispatch(
        _evaluation(),
        action_id="a_ticket",
        endpoint="action://ticket/create",
        payload={"severity": "bad"},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
        now=datetime(2026, 1, 6, 9, 0, 1),
    )

    activity = ledger.get_activity(activity_id)
    assert activity.status == "failed_non_retryable"
    assert len(ledger.get_delivery_logs(activity_id)) == 1


def test_w5_dispatch_retries_to_dlq_and_supports_manual_replay() -> None:
    gateway = ScriptedGateway(
        [
            ActionGatewayResponse(status_code=503, error_code="upstream_503"),
            ActionGatewayResponse(status_code=503, error_code="upstream_503"),
            TimeoutError("timeout"),
            ActionGatewayResponse(status_code=503, error_code="upstream_503"),
            ActionGatewayResponse(status_code=200, execution_id="exec-replayed"),
        ]
    )
    ledger = InMemoryActivityLedger()
    dispatcher = ActionDispatcher(gateway, ledger)

    now = datetime(2026, 1, 6, 9, 0, 0)
    activity_id = dispatcher.dispatch(
        _evaluation(),
        action_id="a_ticket",
        endpoint="action://ticket/create",
        payload={"severity": "high"},
        idempotency_template="${monitorId}:${objectId}:${sourceVersion}:${actionId}",
        now=now,
    )

    dispatcher.process_retry_queue(now=now + timedelta(minutes=1))
    dispatcher.process_retry_queue(now=now + timedelta(minutes=6))
    dispatcher.process_retry_queue(now=now + timedelta(hours=1, minutes=6))

    activity = ledger.get_activity(activity_id)
    assert activity.status == "dead_letter"
    assert activity_id in ledger.list_dlq_activity_ids("t1")

    dispatcher.replay_dead_letter(activity_id, now=now + timedelta(hours=2))
    dispatcher.process_retry_queue(now=now + timedelta(hours=2, minutes=1))

    replayed = ledger.get_activity(activity_id)
    logs = ledger.get_delivery_logs(activity_id)
    assert replayed.status == "succeeded"
    assert replayed.action_execution_id == "exec-replayed"
    assert len(logs) == 5
