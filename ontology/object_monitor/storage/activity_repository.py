from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List

from ontology.object_monitor.storage.models import ActionDeliveryLogRow, MonitorActivityRow


@dataclass(frozen=True)
class ActivityQuery:
    tenant_id: str
    monitor_id: str | None = None
    object_id: str | None = None
    status: str | None = None


class InMemoryActivityLedger:
    def __init__(self) -> None:
        self._activities: Dict[str, MonitorActivityRow] = {}
        self._delivery_logs: Dict[str, List[ActionDeliveryLogRow]] = {}

    def upsert_activity(self, row: MonitorActivityRow) -> None:
        self._activities[row.activity_id] = row

    def update_status(self, activity_id: str, *, status: str, action_execution_id: str | None, updated_at: datetime) -> MonitorActivityRow:
        current = self._activities[activity_id]
        updated = MonitorActivityRow(
            activity_id=current.activity_id,
            tenant_id=current.tenant_id,
            monitor_id=current.monitor_id,
            monitor_version=current.monitor_version,
            object_id=current.object_id,
            source_version=current.source_version,
            status=status,
            action_execution_id=action_execution_id,
            event_time=current.event_time,
            updated_at=updated_at,
        )
        self._activities[activity_id] = updated
        return updated

    def append_delivery_log(self, row: ActionDeliveryLogRow) -> None:
        self._delivery_logs.setdefault(row.activity_id, []).append(row)

    def get_activity(self, activity_id: str) -> MonitorActivityRow:
        return self._activities[activity_id]

    def get_delivery_logs(self, activity_id: str) -> List[ActionDeliveryLogRow]:
        return list(self._delivery_logs.get(activity_id, []))

    def query(self, query: ActivityQuery) -> List[MonitorActivityRow]:
        rows = [row for row in self._activities.values() if row.tenant_id == query.tenant_id]
        if query.monitor_id is not None:
            rows = [row for row in rows if row.monitor_id == query.monitor_id]
        if query.object_id is not None:
            rows = [row for row in rows if row.object_id == query.object_id]
        if query.status is not None:
            rows = [row for row in rows if row.status == query.status]
        return sorted(rows, key=lambda row: row.updated_at, reverse=True)

    def list_dlq_activity_ids(self, tenant_id: str) -> List[str]:
        return [row.activity_id for row in self._activities.values() if row.tenant_id == tenant_id and row.status == "dead_letter"]
