from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Sequence

from .edits import TransactionEdit


class ActionStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    reverted = "reverted"


class ActionStateStatus(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"


class CompensationFunction(Protocol):
    def __call__(self, input_instances: Dict[str, Any], payload: Dict[str, Any]) -> TransactionEdit: ...


class SagaAction(Protocol):
    def __call__(self, input_instances: Dict[str, Any], payload: Dict[str, Any]) -> None: ...


@dataclass
class SagaStep:
    name: str
    action: SagaAction
    compensation: Optional[SagaAction] = None


@dataclass
class FunctionDefinition:
    name: str
    runtime: str
    code_ref: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    version: int = 1


@dataclass
class ActionDefinition:
    name: str
    description: str
    function_name: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    submission_criteria: Optional[Callable[[Dict[str, Any]], bool]] = None
    compensation_fn: Optional[CompensationFunction] = None
    saga_steps: Sequence[SagaStep] = field(default_factory=list)
    version: int = 1
    active: bool = True


@dataclass
class ActionExecution:
    execution_id: str
    action_name: str
    submitter: str
    status: ActionStatus
    submitted_at: datetime
    input_payload: Dict[str, Any]
    output_payload: Dict[str, Any] = field(default_factory=dict)
    ontology_edit: Optional[TransactionEdit] = None
    compensation_edit: Optional[TransactionEdit] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


@dataclass
class ActionState:
    action_id: str
    execution_id: str
    status: ActionStateStatus
    intent_payload: Dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass
class ActionRevert:
    revert_id: str
    original_execution_id: str
    revert_execution_id: str
    status: ActionStatus
    created_at: datetime
    reason: Optional[str] = None


@dataclass
class NotificationLog:
    execution_id: str
    channel: str
    subject: str
    payload: Dict[str, Any]
    created_at: datetime


@dataclass
class ActionLog:
    execution_id: str
    event_type: str
    payload: Dict[str, Any]
    created_at: datetime


@dataclass
class SideEffectOutbox:
    outbox_id: str
    execution_id: str
    effect_type: str
    payload: Dict[str, Any]
    status: str = "pending"
    retry_count: int = 0
    max_retries: int = 3
    next_attempt_at: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
