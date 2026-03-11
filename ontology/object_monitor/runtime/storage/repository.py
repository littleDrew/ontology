from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from ontology.object_monitor.define.api.contracts import EvaluationRecord
from ontology.object_monitor.runtime.storage.models import MonitorEvaluationRow


@dataclass(frozen=True)
class EvaluationQuery:
    tenant_id: str
    monitor_id: str | None = None
    object_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


class InMemoryEvaluationLedger:
    """W4 ledger with idempotent upsert keyed by tenant/monitor/object/source_version."""

    def __init__(self) -> None:
        self._rows_by_key: Dict[Tuple[str, str, str, int], MonitorEvaluationRow] = {}

    def write_idempotent(self, record: EvaluationRecord) -> bool:
        key = (record.tenant_id, record.monitor_id, record.object_id, record.source_version)
        if key in self._rows_by_key:
            return False
        self._rows_by_key[key] = MonitorEvaluationRow(
            tenant_id=record.tenant_id,
            monitor_id=record.monitor_id,
            monitor_version=record.monitor_version,
            object_id=record.object_id,
            source_version=record.source_version,
            result=record.result.value,
            reason=record.reason,
            snapshot_hash=record.snapshot_hash,
            latency_ms=record.latency_ms,
            event_time=record.event_time,
        )
        return True

    def query(self, query: EvaluationQuery) -> List[MonitorEvaluationRow]:
        rows = [row for row in self._rows_by_key.values() if row.tenant_id == query.tenant_id]
        if query.monitor_id is not None:
            rows = [row for row in rows if row.monitor_id == query.monitor_id]
        if query.object_id is not None:
            rows = [row for row in rows if row.object_id == query.object_id]
        if query.start_time is not None:
            rows = [row for row in rows if row.event_time >= query.start_time]
        if query.end_time is not None:
            rows = [row for row in rows if row.event_time <= query.end_time]
        return sorted(rows, key=lambda row: row.event_time, reverse=True)


__all__ = ["EvaluationQuery", "InMemoryEvaluationLedger"]
