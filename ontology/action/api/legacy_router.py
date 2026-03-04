from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .schemas import ActionExecutionResponse, ActionSubmitRequest
from ..storage.repository import ActionRepository
from .service import ActionService


def create_legacy_router(
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
) -> APIRouter:
    """Legacy unversioned action endpoints kept for compatibility."""

    router = APIRouter()

    @router.post("/actions/submit", response_model=ActionExecutionResponse)
    def submit_action(request: ActionSubmitRequest) -> ActionExecutionResponse:
        if action_service is None or repository is None:
            raise HTTPException(status_code=501, detail="Action service not configured")
        definition = repository.get_action(request.action_name, request.version)
        if definition is None:
            raise HTTPException(status_code=404, detail="Action definition not found")
        execution = action_service.submit(definition, request.submitter, request.input_payload)
        return ActionExecutionResponse(
            execution_id=execution.execution_id,
            action_name=execution.action_name,
            status=execution.status.value,
            submitter=execution.submitter,
            submitted_at=execution.submitted_at.isoformat(),
            input_payload=execution.input_payload,
        )

    @router.get("/actions/{execution_id}", response_model=ActionExecutionResponse)
    def get_action_execution(execution_id: str) -> ActionExecutionResponse:
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
