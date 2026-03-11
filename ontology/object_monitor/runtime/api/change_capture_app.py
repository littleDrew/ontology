from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib import request

from fastapi import APIRouter, FastAPI
from pydantic import BaseModel


class StreamsPayloadEnvelope(BaseModel):
    payload: dict[str, Any]


@dataclass
class ChangeCaptureService:
    data_plane_base_url: str | None = None

    def normalize_streams_event(self, envelope: dict[str, Any]) -> dict[str, Any]:
        meta = envelope.get("meta", {})
        payload = envelope.get("payload", {})
        before = (payload.get("before") or {}).get("properties", {})
        after = (payload.get("after") or {}).get("properties", {})
        changed = []
        fields = []
        for key in sorted(set(before.keys()) | set(after.keys())):
            old_v = before.get(key)
            new_v = after.get(key)
            if old_v != new_v:
                fields.append(key)
                changed.append({"field": key, "old_value": old_v, "new_value": new_v})

        timestamp_ms = int(meta.get("timestamp", 0))
        event_time = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
        return {
            "event_id": str(meta.get("txId", "0")),
            "tenant_id": "default",
            "object_type": str((payload.get("after") or {}).get("labels", ["Unknown"])[0]),
            "object_id": str(payload.get("id", "")),
            "source_version": int(meta.get("txId", 0)),
            "object_version": int(meta.get("txId", 0)),
            "changed_fields": fields,
            "event_time": event_time,
            "trace_id": str(meta.get("txId", "0")),
            "change_source": "neo4j_streams",
            "changed_properties": changed,
        }

    def forward(self, event: dict[str, Any]) -> int:
        if not self.data_plane_base_url:
            return 0
        url = f"{self.data_plane_base_url.rstrip('/')}/api/v1/data-plane/events/object-change"
        req = request.Request(
            url,
            data=json.dumps(event).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(req, timeout=5) as resp:
            return resp.getcode()


def create_change_capture_app(service: ChangeCaptureService) -> FastAPI:
    app = FastAPI(title="Neo4j Change Capture API")
    router = APIRouter(prefix="/api/v1/change-capture")

    @router.post("/neo4j/streams")
    def ingest_streams_event(request_body: StreamsPayloadEnvelope) -> dict[str, Any]:
        normalized = service.normalize_streams_event(request_body.payload)
        status = service.forward(normalized)
        return {"event": normalized, "forward_status": status}

    app.include_router(router)
    return app
