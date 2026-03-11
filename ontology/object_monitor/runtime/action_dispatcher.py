from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Protocol
from uuid import uuid4

from ontology.object_monitor.define.api.contracts import EvaluationRecord
from ontology.object_monitor.runtime.storage.activity_repository import InMemoryActivityLedger
from ontology.object_monitor.runtime.storage.models import ActionDeliveryLogRow, MonitorActivityRow


class ActionGateway(Protocol):
    def apply_action(self, *, action_id: str, endpoint: str, payload: dict, idempotency_key: str) -> "ActionGatewayResponse": ...


@dataclass(frozen=True)
class ActionGatewayResponse:
    status_code: int
    execution_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class DispatchEnvelope:
    activity_id: str
    evaluation: EvaluationRecord
    action_id: str
    endpoint: str
    payload: dict
    idempotency_template: str
    attempt: int = 0
    next_attempt_at: datetime | None = None


class ActionDispatcher:
    """W5 dispatcher with retry ladder (1m/5m/1h), DLQ, and manual replay."""

    RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5), timedelta(hours=1)]

    def __init__(self, gateway: ActionGateway, activity_ledger: InMemoryActivityLedger) -> None:
        self._gateway = gateway
        self._activity_ledger = activity_ledger
        self._retry_queue: List[DispatchEnvelope] = []
        self._envelopes: Dict[str, DispatchEnvelope] = {}

    def dispatch(
        self,
        evaluation: EvaluationRecord,
        *,
        action_id: str,
        endpoint: str,
        payload: dict,
        idempotency_template: str,
        now: datetime | None = None,
    ) -> str:
        now = now or datetime.utcnow()
        activity_id = str(uuid4())
        self._activity_ledger.upsert_activity(
            MonitorActivityRow(
                activity_id=activity_id,
                tenant_id=evaluation.tenant_id,
                monitor_id=evaluation.monitor_id,
                monitor_version=evaluation.monitor_version,
                object_id=evaluation.object_id,
                source_version=evaluation.source_version,
                status="queued",
                action_execution_id=None,
                event_time=evaluation.event_time,
                updated_at=now,
            )
        )
        envelope = DispatchEnvelope(
            activity_id=activity_id,
            evaluation=evaluation,
            action_id=action_id,
            endpoint=endpoint,
            payload=payload,
            idempotency_template=idempotency_template,
            attempt=0,
        )
        self._envelopes[activity_id] = envelope
        self._attempt(envelope, now=now)
        return activity_id

    def process_retry_queue(self, *, now: datetime | None = None) -> None:
        now = now or datetime.utcnow()
        pending = sorted(self._retry_queue, key=lambda item: item.next_attempt_at or now)
        self._retry_queue = []
        for envelope in pending:
            if envelope.next_attempt_at and envelope.next_attempt_at > now:
                self._retry_queue.append(envelope)
                continue
            self._attempt(envelope, now=now)

    def replay_dead_letter(self, activity_id: str, *, now: datetime | None = None) -> None:
        now = now or datetime.utcnow()
        envelope = self._envelopes[activity_id]
        self._activity_ledger.update_status(activity_id, status="queued", action_execution_id=None, updated_at=now)
        envelope.attempt = 0
        envelope.next_attempt_at = now
        self._retry_queue.append(envelope)

    def _attempt(self, envelope: DispatchEnvelope, *, now: datetime) -> None:
        envelope.attempt += 1
        self._activity_ledger.update_status(envelope.activity_id, status="executing", action_execution_id=None, updated_at=now)

        idempotency_key = _render_idempotency_key(envelope.idempotency_template, envelope.evaluation, envelope.action_id)
        response: ActionGatewayResponse
        try:
            response = self._gateway.apply_action(
                action_id=envelope.action_id,
                endpoint=envelope.endpoint,
                payload=envelope.payload,
                idempotency_key=idempotency_key,
            )
        except TimeoutError:
            response = ActionGatewayResponse(status_code=599, error_code="timeout", error_message="gateway timeout")

        status = self._handle_response(envelope, response, now)
        self._activity_ledger.append_delivery_log(
            ActionDeliveryLogRow(
                activity_id=envelope.activity_id,
                delivery_attempt=envelope.attempt,
                status=status,
                error_code=response.error_code,
                error_message=response.error_message,
                created_at=now,
            )
        )

    def _handle_response(self, envelope: DispatchEnvelope, response: ActionGatewayResponse, now: datetime) -> str:
        if 200 <= response.status_code < 300:
            self._activity_ledger.update_status(
                envelope.activity_id,
                status="succeeded",
                action_execution_id=response.execution_id,
                updated_at=now,
            )
            return "succeeded"

        if 400 <= response.status_code < 500:
            self._activity_ledger.update_status(
                envelope.activity_id,
                status="failed_non_retryable",
                action_execution_id=response.execution_id,
                updated_at=now,
            )
            return "failed_non_retryable"

        if envelope.attempt <= len(self.RETRY_DELAYS):
            envelope.next_attempt_at = now + self.RETRY_DELAYS[envelope.attempt - 1]
            self._retry_queue.append(envelope)
            self._activity_ledger.update_status(
                envelope.activity_id,
                status="retry_scheduled",
                action_execution_id=response.execution_id,
                updated_at=now,
            )
            return "retry_scheduled"

        self._activity_ledger.update_status(
            envelope.activity_id,
            status="dead_letter",
            action_execution_id=response.execution_id,
            updated_at=now,
        )
        return "dead_letter"


def _render_idempotency_key(template: str, evaluation: EvaluationRecord, action_id: str) -> str:
    return (
        template.replace("${monitorId}", evaluation.monitor_id)
        .replace("${objectId}", evaluation.object_id)
        .replace("${sourceVersion}", str(evaluation.source_version))
        .replace("${actionId}", action_id)
    )
