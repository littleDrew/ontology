from __future__ import annotations

"""SQLAlchemy-backed repositories for object monitor runtime persistence."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, List

from sqlalchemy import and_, create_engine, select
from sqlalchemy.orm import Session

from ontology.object_monitor.define.api.contracts import EvaluationRecord, ObjectChangeEvent
from ontology.object_monitor.runtime.storage.activity_repository import ActivityQuery
from ontology.object_monitor.runtime.storage.models import ActionDeliveryLogRow, MonitorActivityRow, MonitorEvaluationRow
from ontology.object_monitor.runtime.storage.repository import EvaluationQuery
from ontology.object_monitor.persistence.sql_models import (
    ActionDeliveryLogModel,
    Base,
    MonitorActivityModel,
    MonitorEvaluationModel,
    ObjectMonitorOutboxModel,
)


class SqlAlchemyEvaluationLedger:
    """SQLAlchemy implementation of the evaluation ledger query/write APIs."""

    def __init__(self, db_url: str) -> None:
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def write_idempotent(self, record: EvaluationRecord) -> bool:
        with Session(self._engine) as session:
            exists = session.execute(
                select(MonitorEvaluationModel.id).where(
                    and_(
                        MonitorEvaluationModel.tenant_id == record.tenant_id,
                        MonitorEvaluationModel.monitor_id == record.monitor_id,
                        MonitorEvaluationModel.object_id == record.object_id,
                        MonitorEvaluationModel.source_version == record.source_version,
                    )
                )
            ).scalar_one_or_none()
            if exists is not None:
                return False
            session.add(
                MonitorEvaluationModel(
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
            )
            session.commit()
            return True

    def query(self, query: EvaluationQuery) -> List[MonitorEvaluationRow]:
        with Session(self._engine) as session:
            stmt = select(MonitorEvaluationModel).where(MonitorEvaluationModel.tenant_id == query.tenant_id)
            if query.monitor_id is not None:
                stmt = stmt.where(MonitorEvaluationModel.monitor_id == query.monitor_id)
            if query.object_id is not None:
                stmt = stmt.where(MonitorEvaluationModel.object_id == query.object_id)
            if query.start_time is not None:
                stmt = stmt.where(MonitorEvaluationModel.event_time >= query.start_time)
            if query.end_time is not None:
                stmt = stmt.where(MonitorEvaluationModel.event_time <= query.end_time)
            rows = session.execute(stmt.order_by(MonitorEvaluationModel.event_time.desc())).scalars().all()
        return [
            MonitorEvaluationRow(
                tenant_id=row.tenant_id,
                monitor_id=row.monitor_id,
                monitor_version=row.monitor_version,
                object_id=row.object_id,
                source_version=row.source_version,
                result=row.result,
                reason=row.reason,
                snapshot_hash=row.snapshot_hash,
                latency_ms=row.latency_ms,
                event_time=row.event_time,
            )
            for row in rows
        ]


class SqlAlchemyActivityLedger:
    """SQLAlchemy implementation for activity state and delivery logs."""

    def __init__(self, db_url: str) -> None:
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def upsert_activity(self, row: MonitorActivityRow) -> None:
        with Session(self._engine) as session:
            existing = session.get(MonitorActivityModel, row.activity_id)
            if existing is None:
                session.add(MonitorActivityModel(**asdict(row)))
            else:
                existing.status = row.status
                existing.action_execution_id = row.action_execution_id
                existing.updated_at = row.updated_at
            session.commit()

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
        with Session(self._engine) as session:
            session.add(ActionDeliveryLogModel(**asdict(row)))
            session.commit()

    def get_activity(self, activity_id: str) -> MonitorActivityRow:
        with Session(self._engine) as session:
            row = session.get(MonitorActivityModel, activity_id)
            if row is None:
                raise KeyError(f"activity not found: {activity_id}")
            return MonitorActivityRow(
                activity_id=row.activity_id,
                tenant_id=row.tenant_id,
                monitor_id=row.monitor_id,
                monitor_version=row.monitor_version,
                object_id=row.object_id,
                source_version=row.source_version,
                status=row.status,
                action_execution_id=row.action_execution_id,
                event_time=row.event_time,
                updated_at=row.updated_at,
            )

    def get_delivery_logs(self, activity_id: str) -> List[ActionDeliveryLogRow]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(ActionDeliveryLogModel)
                .where(ActionDeliveryLogModel.activity_id == activity_id)
                .order_by(ActionDeliveryLogModel.id.asc())
            ).scalars().all()
            return [
                ActionDeliveryLogRow(
                    activity_id=row.activity_id,
                    delivery_attempt=row.delivery_attempt,
                    status=row.status,
                    error_code=row.error_code,
                    error_message=row.error_message,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    def query(self, query: ActivityQuery) -> List[MonitorActivityRow]:
        with Session(self._engine) as session:
            stmt = select(MonitorActivityModel).where(MonitorActivityModel.tenant_id == query.tenant_id)
            if query.monitor_id is not None:
                stmt = stmt.where(MonitorActivityModel.monitor_id == query.monitor_id)
            if query.object_id is not None:
                stmt = stmt.where(MonitorActivityModel.object_id == query.object_id)
            if query.status is not None:
                stmt = stmt.where(MonitorActivityModel.status == query.status)
            rows = session.execute(stmt.order_by(MonitorActivityModel.updated_at.desc())).scalars().all()
            return [
                MonitorActivityRow(
                    activity_id=row.activity_id,
                    tenant_id=row.tenant_id,
                    monitor_id=row.monitor_id,
                    monitor_version=row.monitor_version,
                    object_id=row.object_id,
                    source_version=row.source_version,
                    status=row.status,
                    action_execution_id=row.action_execution_id,
                    event_time=row.event_time,
                    updated_at=row.updated_at,
                )
                for row in rows
            ]

    def list_dlq_activity_ids(self, tenant_id: str) -> List[str]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(MonitorActivityModel.activity_id)
                .where(and_(MonitorActivityModel.tenant_id == tenant_id, MonitorActivityModel.status == "dead_letter"))
                .order_by(MonitorActivityModel.updated_at.desc())
            ).all()
            return [row[0] for row in rows]


class SqlAlchemyChangeOutboxRepository:
    """SQL-backed outbox repository used by dual-channel ingestion."""

    def __init__(self, db_url: str) -> None:
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def add(self, event: ObjectChangeEvent, source: str = "outbox") -> None:
        payload = asdict(event)
        payload["event_time"] = event.event_time.isoformat()
        with Session(self._engine) as session:
            exists = session.execute(select(ObjectMonitorOutboxModel.id).where(ObjectMonitorOutboxModel.event_id == event.event_id)).scalar_one_or_none()
            if exists is not None:
                return
            session.add(ObjectMonitorOutboxModel(event_id=event.event_id, payload=payload, source=source, status="pending"))
            session.commit()

    def claim_pending(self, limit: int = 100) -> List[ObjectChangeEvent]:
        with Session(self._engine) as session:
            rows = session.execute(
                select(ObjectMonitorOutboxModel)
                .where(ObjectMonitorOutboxModel.status == "pending")
                .order_by(ObjectMonitorOutboxModel.created_at.asc())
                .limit(limit)
            ).scalars().all()
            events: list[ObjectChangeEvent] = []
            for row in rows:
                row.status = "published"
                row.published_at = datetime.utcnow()
                payload = dict(row.payload)
                payload["event_time"] = _ensure_dt(payload["event_time"])
                events.append(ObjectChangeEvent(**payload))
            session.commit()
            return events


def _ensure_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
