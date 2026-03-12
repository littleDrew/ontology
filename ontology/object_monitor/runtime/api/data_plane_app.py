from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel, Field

from ontology.object_monitor.define.api.contracts import EvaluationResult, MonitorArtifact, ObjectChangeEvent, PropertyChange
from ontology.object_monitor.runtime.action_dispatcher import ActionDispatcher
from ontology.object_monitor.runtime.event_filter import EventFilter, MonitorRuntimeSpec
from ontology.object_monitor.runtime.evaluator import L1Evaluator
from ontology.object_monitor.runtime.storage.activity_repository import ActivityQuery, InMemoryActivityLedger
from ontology.object_monitor.runtime.storage.repository import EvaluationQuery, InMemoryEvaluationLedger


class PropertyChangeRequest(BaseModel):
    field: str
    old_value: Any = None
    new_value: Any = None


class ObjectChangeEventRequest(BaseModel):
    event_id: str
    tenant_id: str = "global"
    object_type: str
    object_id: str
    source_version: int
    object_version: int
    changed_fields: list[str]
    event_time: datetime
    trace_id: str
    change_source: str = "outbox"
    changed_properties: list[PropertyChangeRequest] = Field(default_factory=list)


class ArtifactReloadRequest(BaseModel):
    artifacts: list[dict]


@dataclass
class ObjectMonitorDataPlaneService:
    context_builder: Any
    event_filter: EventFilter
    evaluator: L1Evaluator
    dispatcher: ActionDispatcher
    evaluation_ledger: InMemoryEvaluationLedger
    activity_ledger: InMemoryActivityLedger

    def reload_artifacts(self, artifacts: list[MonitorArtifact]) -> int:
        specs = [
            MonitorRuntimeSpec(artifact=a, object_type=a.object_type, watched_fields=set(a.field_projection))
            for a in artifacts
        ]
        self.event_filter.load_specs(specs)
        return len(specs)

    def process_event(self, event: ObjectChangeEvent) -> dict[str, Any]:
        snapshot = self.context_builder.store.get(event.tenant_id, event.object_type, event.object_id)
        payload = dict(snapshot.payload) if snapshot else {}
        for prop in event.changed_properties:
            payload[prop.field] = prop.new_value
        self.context_builder.build(event, object_payload=payload)
        candidates = self.event_filter.filter_candidates(event, payload)
        evaluations = self.evaluator.evaluate_l1(event, candidates)

        activity_ids: list[str] = []
        for record in evaluations:
            if record.result is not EvaluationResult.hit:
                continue
            for artifact in candidates:
                if artifact.monitor_id != record.monitor_id:
                    continue
                for action in artifact.action_templates:
                    action_ref = str(action.get("action_ref", ""))
                    action_id = action_ref.split("action://")[-1].strip("/").replace("/", "_")
                    aid = self.dispatcher.dispatch(
                        record,
                        action_id=action_id,
                        endpoint="/api/v1/actions/apply",
                        payload=dict(action.get("parameters", {})),
                        idempotency_template=str(
                            action.get(
                                "idempotency_key_template",
                                "${monitorId}:${objectId}:${sourceVersion}:${actionId}",
                            )
                        ),
                    )
                    activity_ids.append(aid)

        return {
            "accepted": True,
            "candidate_count": len(candidates),
            "evaluation_count": len(evaluations),
            "activity_ids": activity_ids,
        }


def create_object_monitor_data_plane_app(service: ObjectMonitorDataPlaneService) -> FastAPI:
    app = FastAPI(title="Object Monitor Data Plane API")
    router = APIRouter(prefix="/api/v1/data-plane")

    @router.post("/reload-artifacts")
    def reload_artifacts(request: ArtifactReloadRequest) -> dict[str, int]:
        artifacts = [MonitorArtifact(**raw) for raw in request.artifacts]
        loaded = service.reload_artifacts(artifacts)
        return {"loaded": loaded}

    @router.post("/events/object-change")
    def ingest_event(request: ObjectChangeEventRequest) -> dict[str, Any]:
        event = ObjectChangeEvent(
            event_id=request.event_id,
            tenant_id=request.tenant_id,
            object_type=request.object_type,
            object_id=request.object_id,
            source_version=request.source_version,
            object_version=request.object_version,
            changed_fields=request.changed_fields,
            event_time=request.event_time,
            trace_id=request.trace_id,
            change_source=request.change_source,
            changed_properties=[
                PropertyChange(field=item.field, old_value=item.old_value, new_value=item.new_value)
                for item in request.changed_properties
            ],
        )
        return service.process_event(event)

    @router.get("/evaluations")
    def list_evaluations(tenant_id: str, monitor_id: str | None = None, object_id: str | None = None) -> list[dict[str, Any]]:
        rows = service.evaluation_ledger.query(EvaluationQuery(tenant_id=tenant_id, monitor_id=monitor_id, object_id=object_id))
        return [row.__dict__ for row in rows]

    @router.get("/activities")
    def list_activities(tenant_id: str, monitor_id: str | None = None, object_id: str | None = None) -> list[dict[str, Any]]:
        rows = service.activity_ledger.query(ActivityQuery(tenant_id=tenant_id, monitor_id=monitor_id, object_id=object_id))
        return [row.__dict__ for row in rows]

    app.include_router(router)
    return app
