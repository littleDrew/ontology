from __future__ import annotations

from fastapi import FastAPI, HTTPException, Query

from .api_models import ActionExecutionResponse, ActionSubmitRequest, ObjectResponse
from .edits import ObjectLocator
from .storage import GraphStore
from .action_repository import ActionRepository
from .action_service import ActionService


def create_app(
    store: GraphStore,
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
) -> FastAPI:
    app = FastAPI(title="Ontology API")

    @app.get("/objects/{object_type}/{primary_key}", response_model=ObjectResponse)
    def get_object(object_type: str, primary_key: str) -> ObjectResponse:
        try:
            instance = store.get_object(ObjectLocator(object_type, primary_key))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ObjectResponse(
            object_type=instance.object_type,
            primary_key=instance.primary_key,
            properties=instance.properties,
            version=instance.version,
        )

    @app.get("/objects/{object_type}", response_model=list[ObjectResponse])
    def list_objects(
        object_type: str,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> list[ObjectResponse]:
        instances = store.list_objects(object_type, limit=limit, offset=offset)
        return [
            ObjectResponse(
                object_type=instance.object_type,
                primary_key=instance.primary_key,
                properties=instance.properties,
                version=instance.version,
            )
            for instance in instances
        ]

    @app.post("/actions/submit", response_model=ActionExecutionResponse)
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

    @app.get("/actions/{execution_id}", response_model=ActionExecutionResponse)
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

    return app
