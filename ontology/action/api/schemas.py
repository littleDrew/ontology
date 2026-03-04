from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class ObjectResponse(BaseModel):
    object_type: str
    primary_key: str
    properties: Dict[str, Any]
    version: Optional[int]


class ActionApplyRequest(BaseModel):
    submitter: str
    input_payload: Dict[str, Any]
    input_instances: Optional[Dict[str, Dict[str, Any]]] = None
    version: Optional[int] = None
    client_request_id: Optional[str] = None


class ActionSubmitRequest(BaseModel):
    action_name: str
    version: Optional[int] = None
    submitter: str
    input_payload: Dict[str, Any]


class ActionExecutionResponse(BaseModel):
    execution_id: str
    action_name: str
    status: str
    submitter: str
    submitted_at: str
    input_payload: Dict[str, Any]
