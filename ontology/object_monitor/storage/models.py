from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class MonitorEvaluationRow:
    tenant_id: str
    monitor_id: str
    monitor_version: int
    object_id: str
    source_version: int
    result: str
    reason: str
    snapshot_hash: str
    latency_ms: int
    event_time: datetime


@dataclass(frozen=True)
class MonitorActivityRow:
    activity_id: str
    tenant_id: str
    monitor_id: str
    monitor_version: int
    object_id: str
    source_version: int
    status: str
    action_execution_id: str | None
    event_time: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ActionDeliveryLogRow:
    activity_id: str
    delivery_attempt: int
    status: str
    error_code: str | None
    error_message: str | None
    created_at: datetime
