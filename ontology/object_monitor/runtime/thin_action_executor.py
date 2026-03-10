from __future__ import annotations

from dataclasses import dataclass

from ontology.object_monitor.api.contracts import EvaluationRecord

from .action_dispatcher import ActionGateway, ActionGatewayResponse


@dataclass(frozen=True)
class ThinActionExecutionResult:
    success: bool
    status_code: int
    execution_id: str | None
    error_code: str | None = None
    error_message: str | None = None


class ThinActionExecutor:
    """Phase-1 trimmed action executor: sync call only, no retry topic/DLQ/activity ledger."""

    def __init__(self, gateway: ActionGateway) -> None:
        self._gateway = gateway

    def execute(
        self,
        evaluation: EvaluationRecord,
        *,
        action_id: str,
        endpoint: str,
        payload: dict,
        idempotency_template: str,
    ) -> ThinActionExecutionResult:
        idempotency_key = _render_idempotency_key(idempotency_template, evaluation, action_id)
        try:
            response = self._gateway.apply_action(
                action_id=action_id,
                endpoint=endpoint,
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except TimeoutError:
            response = ActionGatewayResponse(status_code=599, error_code="timeout", error_message="gateway timeout")

        return ThinActionExecutionResult(
            success=200 <= response.status_code < 300,
            status_code=response.status_code,
            execution_id=response.execution_id,
            error_code=response.error_code,
            error_message=response.error_message,
        )


def _render_idempotency_key(template: str, evaluation: EvaluationRecord, action_id: str) -> str:
    return (
        template.replace("${monitorId}", evaluation.monitor_id)
        .replace("${objectId}", evaluation.object_id)
        .replace("${sourceVersion}", str(evaluation.source_version))
        .replace("${actionId}", action_id)
    )
