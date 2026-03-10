from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List


class EvaluationResult(str, Enum):
    hit = "HIT"
    miss = "MISS"


class MonitorVersionStatus(str, Enum):
    draft = "draft"
    active = "active"
    archived = "archived"


@dataclass(frozen=True)
class PropertyChange:
    field: str
    old_value: Any
    new_value: Any


@dataclass(frozen=True)
class ObjectChangeEvent:
    event_id: str
    tenant_id: str
    object_type: str
    object_id: str
    source_version: int
    object_version: int
    changed_fields: List[str]
    event_time: datetime
    trace_id: str
    change_source: str = "outbox"
    changed_properties: List[PropertyChange] = field(default_factory=list)


@dataclass(frozen=True)
class ReconcileEvent:
    tenant_id: str
    object_type: str
    object_id: str
    expected_version: int
    actual_version: int
    reason: str
    trace_id: str


@dataclass(frozen=True)
class MonitorEnvelope:
    id: str
    object_type: str
    scope: str = ""


@dataclass(frozen=True)
class InputBinding:
    fields: List[str]


@dataclass(frozen=True)
class ConditionDefinition:
    expr: str


@dataclass(frozen=True)
class ActionEffect:
    endpoint: str
    idempotency_key: str


@dataclass(frozen=True)
class EffectDefinition:
    action: ActionEffect


@dataclass(frozen=True)
class MonitorDefinition:
    monitor: MonitorEnvelope
    input: InputBinding
    condition: ConditionDefinition
    effect: EffectDefinition


@dataclass(frozen=True)
class MonitorArtifact:
    monitor_id: str
    monitor_version: int
    plan_hash: str
    field_projection: List[str]
    predicate_ast: Dict[str, Any]
    action_template: Dict[str, Any]
    limits: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvaluationRecord:
    evaluation_id: str
    tenant_id: str
    monitor_id: str
    monitor_version: int
    object_id: str
    source_version: int
    result: EvaluationResult
    reason: str
    snapshot_hash: str
    latency_ms: int
    event_time: datetime


@dataclass(frozen=True)
class ActivityRecord:
    activity_id: str
    tenant_id: str
    monitor_id: str
    monitor_version: int
    object_id: str
    source_version: int
    action_status: str
    action_execution_id: str | None
    updated_at: datetime


@dataclass(frozen=True)
class MonitorVersionRecord:
    monitor_id: str
    monitor_version: int
    plan_hash: str
    status: MonitorVersionStatus
    command_id: str
    operator: str
    created_at: datetime
    published_at: datetime | None = None
    rollback_from_version: int | None = None
