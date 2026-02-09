from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class ObjectResponse(BaseModel):
    object_type: str
    primary_key: str
    properties: Dict[str, Any]
    version: Optional[int]


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
