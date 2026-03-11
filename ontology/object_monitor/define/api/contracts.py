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
class GeneralDefinition:
    name: str
    description: str
    object_type: str
    enabled: bool = True


@dataclass(frozen=True)
class ObjectSetDefinition:
    type: str
    properties: List[str]
    scope: str = ""


@dataclass(frozen=True)
class RuleDefinition:
    expression: str


@dataclass(frozen=True)
class ConditionDefinition:
    object_set: ObjectSetDefinition
    rule: RuleDefinition


@dataclass(frozen=True)
class ActionDefinition:
    name: str
    action_ref: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MonitorDefinition:
    general: GeneralDefinition
    condition: ConditionDefinition
    actions: List[ActionDefinition]


@dataclass(frozen=True)
class MonitorArtifact:
    monitor_id: str
    monitor_version: int
    plan_hash: str
    object_type: str
    scope_predicate_ast: Dict[str, Any]
    field_projection: List[str]
    rule_predicate_ast: Dict[str, Any]
    action_templates: List[Dict[str, Any]]
    runtime_policy: Dict[str, Any] = field(default_factory=dict)


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
