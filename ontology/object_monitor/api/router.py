from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ontology.object_monitor.api.contracts import MonitorVersionRecord
from ontology.object_monitor.api.service import InMemoryMonitorReleaseService
from ontology.object_monitor.runtime.event_filter import EventFilter, MonitorRuntimeSpec


class MonitorUpsertRequest(BaseModel):
    payload: dict
    available_fields: list[str] = Field(default_factory=list)
    operator: str
    limits: dict | None = None


class MonitorPublishRequest(BaseModel):
    operator: str


class MonitorRollbackRequest(BaseModel):
    target_version: int
    operator: str


class MonitorVersionResponse(BaseModel):
    monitor_id: str
    monitor_version: int
    plan_hash: str
    status: str
    command_id: str
    operator: str
    created_at: str
    published_at: str | None = None
    rollback_from_version: int | None = None


def create_router(release_service: InMemoryMonitorReleaseService, event_filter: EventFilter) -> APIRouter:
    """Control-plane API for monitor definition/publish/rollback."""

    router = APIRouter()

    @router.post("/monitors", response_model=MonitorVersionResponse)
    def create_monitor_definition(request: MonitorUpsertRequest) -> MonitorVersionResponse:
        record = release_service.create_definition(
            request.payload,
            available_fields=request.available_fields,
            operator=request.operator,
            limits=request.limits,
        )
        return _to_response(record)

    @router.post("/monitors/{monitor_id}/versions/{monitor_version}/publish", response_model=MonitorVersionResponse)
    def publish_monitor(monitor_id: str, monitor_version: int, request: MonitorPublishRequest) -> MonitorVersionResponse:
        try:
            record = release_service.publish(monitor_id, monitor_version, operator=request.operator)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _reload_event_filter(release_service, event_filter)
        return _to_response(record)

    @router.post("/monitors/{monitor_id}/rollback", response_model=MonitorVersionResponse)
    def rollback_monitor(monitor_id: str, request: MonitorRollbackRequest) -> MonitorVersionResponse:
        try:
            record = release_service.rollback(
                monitor_id,
                request.target_version,
                operator=request.operator,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        _reload_event_filter(release_service, event_filter)
        return _to_response(record)

    return router


def _reload_event_filter(release_service: InMemoryMonitorReleaseService, event_filter: EventFilter) -> None:
    specs = [
        MonitorRuntimeSpec(
            artifact=artifact,
            object_type=artifact.object_type,
            watched_fields=set(artifact.field_projection),
        )
        for artifact in release_service.list_active_artifacts()
    ]
    event_filter.load_specs(specs)


def _to_response(record: MonitorVersionRecord) -> MonitorVersionResponse:
    return MonitorVersionResponse(
        monitor_id=record.monitor_id,
        monitor_version=record.monitor_version,
        plan_hash=record.plan_hash,
        status=record.status.value,
        command_id=record.command_id,
        operator=record.operator,
        created_at=record.created_at.isoformat(),
        published_at=record.published_at.isoformat() if record.published_at else None,
        rollback_from_version=record.rollback_from_version,
    )
