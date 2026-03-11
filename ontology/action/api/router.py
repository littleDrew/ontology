from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .schemas import ActionApplyRequest, ActionExecutionResponse
from .domain_models import ActionDefinition, ActionExecutionMode, ActionTargetType
from ..storage.repository import ActionRepository
from .service import ActionService



class ActionCreateRequest(BaseModel):
    action_id: str = Field(min_length=1)
    description: str = ""
    function_name: str = Field(min_length=1)
    version: int = 1
    active: bool = True
    execution_mode: ActionExecutionMode = ActionExecutionMode.in_process
    target_type: ActionTargetType | None = None
    target_api_name: str | None = None


class ActionDefinitionResponse(BaseModel):
    action_id: str
    function_name: str
    version: int
    active: bool

def create_router(
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
) -> APIRouter:
    """Create v1 action routes for apply and execution query."""

    router = APIRouter()

    @router.post("/actions", response_model=ActionDefinitionResponse)
    def create_action(request: ActionCreateRequest) -> ActionDefinitionResponse:
        if repository is None:
            raise HTTPException(status_code=501, detail="Action repository not configured")
        existing = repository.get_action(request.action_id, request.version)
        if existing is not None:
            raise HTTPException(status_code=409, detail="Action definition already exists")

        definition = ActionDefinition(
            name=request.action_id,
            description=request.description,
            function_name=request.function_name,
            version=request.version,
            active=request.active,
            execution_mode=request.execution_mode,
            target_type=request.target_type,
            target_api_name=request.target_api_name,
        )
        repository.add_action(definition)
        return ActionDefinitionResponse(
            action_id=definition.name,
            function_name=definition.function_name,
            version=definition.version,
            active=definition.active,
        )

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
