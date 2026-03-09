from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List

from ontology.object_monitor.api.contracts import EvaluationRecord
from ontology.object_monitor.storage.activity_repository import ActivityQuery
from ontology.object_monitor.storage.models import ActionDeliveryLogRow, MonitorActivityRow, MonitorEvaluationRow
from ontology.object_monitor.storage.repository import EvaluationQuery


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


class SqliteEvaluationLedger:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn_obj: sqlite3.Connection | None = None
        else:
            self._conn_obj = sqlite3.connect(":memory:")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._conn_obj is not None:
            return self._conn_obj
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_evaluation (
                  tenant_id TEXT NOT NULL,
                  monitor_id TEXT NOT NULL,
                  monitor_version INTEGER NOT NULL,
                  object_id TEXT NOT NULL,
                  source_version INTEGER NOT NULL,
                  result TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  snapshot_hash TEXT NOT NULL,
                  latency_ms INTEGER NOT NULL,
                  event_time TEXT NOT NULL,
                  PRIMARY KEY (tenant_id, monitor_id, object_id, source_version)
                )
                """
            )

    def write_idempotent(self, record: EvaluationRecord) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO monitor_evaluation
                (tenant_id, monitor_id, monitor_version, object_id, source_version, result, reason, snapshot_hash, latency_ms, event_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.tenant_id,
                    record.monitor_id,
                    record.monitor_version,
                    record.object_id,
                    record.source_version,
                    record.result.value,
                    record.reason,
                    record.snapshot_hash,
                    record.latency_ms,
                    _iso(record.event_time),
                ),
            )
            return cur.rowcount == 1

    def query(self, query: EvaluationQuery) -> List[MonitorEvaluationRow]:
        clauses = ["tenant_id = ?"]
        params: list[object] = [query.tenant_id]
        if query.monitor_id is not None:
            clauses.append("monitor_id = ?")
            params.append(query.monitor_id)
        if query.object_id is not None:
            clauses.append("object_id = ?")
            params.append(query.object_id)
        if query.start_time is not None:
            clauses.append("event_time >= ?")
            params.append(_iso(query.start_time))
        if query.end_time is not None:
            clauses.append("event_time <= ?")
            params.append(_iso(query.end_time))
        sql = (
            "SELECT tenant_id, monitor_id, monitor_version, object_id, source_version, result, reason, snapshot_hash, latency_ms, event_time "
            "FROM monitor_evaluation WHERE " + " AND ".join(clauses) + " ORDER BY event_time DESC"
        )
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MonitorEvaluationRow(
                tenant_id=row[0],
                monitor_id=row[1],
                monitor_version=row[2],
                object_id=row[3],
                source_version=row[4],
                result=row[5],
                reason=row[6],
                snapshot_hash=row[7],
                latency_ms=row[8],
                event_time=_dt(row[9]),
            )
            for row in rows
        ]


class SqliteActivityLedger:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn_obj: sqlite3.Connection | None = None
        else:
            self._conn_obj = sqlite3.connect(":memory:")
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        if self._conn_obj is not None:
            return self._conn_obj
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_activity (
                  activity_id TEXT PRIMARY KEY,
                  tenant_id TEXT NOT NULL,
                  monitor_id TEXT NOT NULL,
                  monitor_version INTEGER NOT NULL,
                  object_id TEXT NOT NULL,
                  source_version INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  action_execution_id TEXT,
                  event_time TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS action_delivery_log (
                  id INTEGER PRIMARY KEY AUTOINCREMENT,
                  activity_id TEXT NOT NULL,
                  delivery_attempt INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  error_code TEXT,
                  error_message TEXT,
                  created_at TEXT NOT NULL
                )
                """
            )

    def upsert_activity(self, row: MonitorActivityRow) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO monitor_activity(activity_id, tenant_id, monitor_id, monitor_version, object_id, source_version, status, action_execution_id, event_time, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(activity_id) DO UPDATE SET
                  status=excluded.status,
                  action_execution_id=excluded.action_execution_id,
                  updated_at=excluded.updated_at
                """,
                (
                    row.activity_id,
                    row.tenant_id,
                    row.monitor_id,
                    row.monitor_version,
                    row.object_id,
                    row.source_version,
                    row.status,
                    row.action_execution_id,
                    _iso(row.event_time),
                    _iso(row.updated_at),
                ),
            )

    def update_status(self, activity_id: str, *, status: str, action_execution_id: str | None, updated_at: datetime) -> MonitorActivityRow:
        current = self.get_activity(activity_id)
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
        self.upsert_activity(updated)
        return updated

    def append_delivery_log(self, row: ActionDeliveryLogRow) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO action_delivery_log(activity_id, delivery_attempt, status, error_code, error_message, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (row.activity_id, row.delivery_attempt, row.status, row.error_code, row.error_message, _iso(row.created_at)),
            )

    def get_activity(self, activity_id: str) -> MonitorActivityRow:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT activity_id, tenant_id, monitor_id, monitor_version, object_id, source_version, status, action_execution_id, event_time, updated_at FROM monitor_activity WHERE activity_id = ?",
                (activity_id,),
            ).fetchone()
        if row is None:
            raise KeyError(activity_id)
        return MonitorActivityRow(
            activity_id=row[0], tenant_id=row[1], monitor_id=row[2], monitor_version=row[3], object_id=row[4], source_version=row[5], status=row[6], action_execution_id=row[7], event_time=_dt(row[8]), updated_at=_dt(row[9])
        )

    def get_delivery_logs(self, activity_id: str) -> List[ActionDeliveryLogRow]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT activity_id, delivery_attempt, status, error_code, error_message, created_at FROM action_delivery_log WHERE activity_id = ? ORDER BY id ASC",
                (activity_id,),
            ).fetchall()
        return [
            ActionDeliveryLogRow(activity_id=row[0], delivery_attempt=row[1], status=row[2], error_code=row[3], error_message=row[4], created_at=_dt(row[5]))
            for row in rows
        ]

    def query(self, query: ActivityQuery) -> List[MonitorActivityRow]:
        clauses = ["tenant_id = ?"]
        params: list[object] = [query.tenant_id]
        if query.monitor_id is not None:
            clauses.append("monitor_id = ?")
            params.append(query.monitor_id)
        if query.object_id is not None:
            clauses.append("object_id = ?")
            params.append(query.object_id)
        if query.status is not None:
            clauses.append("status = ?")
            params.append(query.status)
        sql = "SELECT activity_id, tenant_id, monitor_id, monitor_version, object_id, source_version, status, action_execution_id, event_time, updated_at FROM monitor_activity WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC"
        with self._conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            MonitorActivityRow(
                activity_id=row[0], tenant_id=row[1], monitor_id=row[2], monitor_version=row[3], object_id=row[4], source_version=row[5], status=row[6], action_execution_id=row[7], event_time=_dt(row[8]), updated_at=_dt(row[9])
            )
            for row in rows
        ]

    def list_dlq_activity_ids(self, tenant_id: str) -> List[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT activity_id FROM monitor_activity WHERE tenant_id = ? AND status = 'dead_letter' ORDER BY updated_at DESC",
                (tenant_id,),
            ).fetchall()
        return [row[0] for row in rows]
