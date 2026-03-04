from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .schemas import ActionApplyRequest, ActionExecutionResponse
from ..storage.repository import ActionRepository
from .service import ActionService


def create_router(
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
) -> APIRouter:
    """Create v1 action routes for apply and execution query."""

    router = APIRouter()

    @router.post("/actions/{action_id}/apply", response_model=ActionExecutionResponse)
    def apply_action(action_id: str, request: ActionApplyRequest) -> ActionExecutionResponse:
        """Apply an action definition end-to-end (submit + execute + apply)."""
        if action_service is None or repository is None:
            raise HTTPException(status_code=501, detail="Action service not configured")
        definition = repository.get_action(action_id, request.version)
        if definition is None:
            raise HTTPException(status_code=404, detail="Action definition not found")
        try:
            execution = action_service.apply(
                action_name=action_id,
                submitter=request.submitter,
                input_payload=request.input_payload,
                version=request.version,
                input_instance_locators=request.input_instances,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return ActionExecutionResponse(
            execution_id=execution.execution_id,
            action_name=execution.action_name,
            status=execution.status.value,
            submitter=execution.submitter,
            submitted_at=execution.submitted_at.isoformat(),
            input_payload=execution.input_payload,
        )

    @router.get("/actions/executions/{execution_id}", response_model=ActionExecutionResponse)
    def get_action_execution(execution_id: str) -> ActionExecutionResponse:
        """Fetch one action execution by id."""
        if repository is None:
            raise HTTPException(status_code=501, detail="Action repository not configured")
        execution = repository.get_execution(execution_id)
        if execution is None:
            raise HTTPException(status_code=404, detail="Action execution not found")
        return ActionExecutionResponse(
            execution_id=execution.execution_id,
            action_name=execution.action_name,
            status=execution.status.value,
            submitter=execution.submitter,
            submitted_at=execution.submitted_at.isoformat(),
            input_payload=execution.input_payload,
        )

    return router
