from __future__ import annotations

"""SQLAlchemy-backed repositories for object monitor persistence."""

from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, List
from uuid import uuid4

from sqlalchemy import and_, create_engine, select, update
from sqlalchemy.orm import Session

from ontology.object_monitor.api.contracts import (
    EvaluationRecord,
    MonitorArtifact,
    MonitorDefinition,
    MonitorVersionRecord,
    MonitorVersionStatus,
    ObjectChangeEvent,
)
from ontology.object_monitor.compiler.dsl import ValidationContext, parse_monitor_definition, validate_monitor_definition
from ontology.object_monitor.compiler.service import build_monitor_artifact
from ontology.object_monitor.storage.activity_repository import ActivityQuery
from ontology.object_monitor.storage.models import ActionDeliveryLogRow, MonitorActivityRow, MonitorEvaluationRow
from ontology.object_monitor.storage.repository import EvaluationQuery
from ontology.object_monitor.storage.sql_models import (
    ActionDeliveryLogModel,
    Base,
    MonitorActivityModel,
    MonitorEvaluationModel,
    MonitorVersionModel,
    ObjectMonitorOutboxModel,
)


class SqlAlchemyMonitorReleaseService:
    """Persist monitor definitions, publish state and rollback metadata."""
    def __init__(self, db_url: str) -> None:
        """Initialize the database engine and ensure monitor tables exist."""
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def create_definition(
        self,
        payload: dict[str, Any],
        *,
        available_fields: Iterable[str],
        operator: str,
        limits: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MonitorVersionRecord:
        """Validate and persist a new draft monitor definition/version."""
        parsed = parse_monitor_definition(payload)
        validate_monitor_definition(parsed, ValidationContext(available_fields=available_fields))
        now = now or datetime.utcnow()

        with Session(self._engine) as session:
            existing = session.execute(
                select(MonitorVersionModel.monitor_version)
                .where(MonitorVersionModel.monitor_id == parsed.monitor.id)
                .order_by(MonitorVersionModel.monitor_version.desc())
                .limit(1)
            ).scalar_one_or_none()
            next_version = (existing or 0) + 1
            artifact = build_monitor_artifact(parsed, monitor_version=next_version, limits=limits)
            record = MonitorVersionModel(
                monitor_id=parsed.monitor.id,
                monitor_version=next_version,
                plan_hash=artifact.plan_hash,
                status=MonitorVersionStatus.draft.value,
                command_id=f"cmd-{uuid4()}",
                operator=operator,
                definition_json=asdict(parsed),
                artifact_json=asdict(artifact),
                created_at=now,
            )
            session.add(record)
            session.commit()
            return _to_version_record(record)

    def publish(self, monitor_id: str, monitor_version: int, *, operator: str, now: datetime | None = None) -> MonitorVersionRecord:
        """Mark a specific monitor version as active and archive previous active."""
        now = now or datetime.utcnow()
        with Session(self._engine) as session:
            target = _require_version(session, monitor_id, monitor_version)
            session.execute(
                update(MonitorVersionModel)
                .where(and_(MonitorVersionModel.monitor_id == monitor_id, MonitorVersionModel.status == MonitorVersionStatus.active.value))
                .values(status=MonitorVersionStatus.archived.value)
            )
            target.status = MonitorVersionStatus.active.value
            target.operator = operator
            target.command_id = f"cmd-{uuid4()}"
            target.published_at = now
            session.commit()
            session.refresh(target)
            return _to_version_record(target)

    def rollback(self, monitor_id: str, target_version: int, *, operator: str, now: datetime | None = None) -> MonitorVersionRecord:
        """Create a new active version by copying a historical target version."""
        now = now or datetime.utcnow()
        with Session(self._engine) as session:
            source = _require_version(session, monitor_id, target_version)
            latest = session.execute(
                select(MonitorVersionModel.monitor_version)
                .where(MonitorVersionModel.monitor_id == monitor_id)
                .order_by(MonitorVersionModel.monitor_version.desc())
                .limit(1)
            ).scalar_one()
            new_version = latest + 1
            artifact = dict(source.artifact_json)
            artifact["monitor_version"] = new_version

            session.execute(
                update(MonitorVersionModel)
                .where(and_(MonitorVersionModel.monitor_id == monitor_id, MonitorVersionModel.status == MonitorVersionStatus.active.value))
                .values(status=MonitorVersionStatus.archived.value)
            )
            row = MonitorVersionModel(
                monitor_id=monitor_id,
                monitor_version=new_version,
                plan_hash=source.plan_hash,
                status=MonitorVersionStatus.active.value,
                command_id=f"cmd-{uuid4()}",
                operator=operator,
                definition_json=dict(source.definition_json),
                artifact_json=artifact,
                created_at=now,
                published_at=now,
                rollback_from_version=target_version,
            )
            session.add(row)
            session.commit()
            return _to_version_record(row)

    def get_active_artifact(self, monitor_id: str) -> MonitorArtifact:
        """Load the latest active compiled artifact for a monitor."""
        with Session(self._engine) as session:
            row = session.execute(
                select(MonitorVersionModel)
                .where(and_(MonitorVersionModel.monitor_id == monitor_id, MonitorVersionModel.status == MonitorVersionStatus.active.value))
                .order_by(MonitorVersionModel.monitor_version.desc())
                .limit(1)
            ).scalar_one()
            return MonitorArtifact(**row.artifact_json)


class SqlAlchemyEvaluationLedger:
    """SQLAlchemy implementation of the evaluation ledger query/write APIs."""
    def __init__(self, db_url: str) -> None:
        """Initialize the database engine and ensure monitor tables exist."""
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def write_idempotent(self, record: EvaluationRecord) -> bool:
        """Persist only when the event has not been evaluated before."""
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
        """Query evaluation records by tenant and optional monitor/object filters."""
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
        """Initialize the database engine and ensure monitor tables exist."""
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def upsert_activity(self, row: MonitorActivityRow) -> None:
        """Insert or update an activity row keyed by activity_id."""
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
        """Convenience helper to update an activity status snapshot."""
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
        """Append one delivery attempt log entry for an activity."""
        with Session(self._engine) as session:
            session.add(ActionDeliveryLogModel(**asdict(row)))
            session.commit()

    def get_activity(self, activity_id: str) -> MonitorActivityRow:
        """Fetch a single activity row by id."""
        with Session(self._engine) as session:
            row = session.get(MonitorActivityModel, activity_id)
            if row is None:
                raise KeyError(activity_id)
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
        """List all delivery log rows for an activity in attempt order."""
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
        """Query activities with optional monitor/object/status filters."""
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
        """Return activity ids currently parked in dead-letter status."""
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
        """Initialize the database engine and ensure monitor tables exist."""
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def add(self, event: ObjectChangeEvent, source: str = "outbox") -> None:
        """Insert a new outbox event if event_id has not been seen."""
        payload = asdict(event)
        payload["event_time"] = event.event_time.isoformat()
        with Session(self._engine) as session:
            exists = session.execute(select(ObjectMonitorOutboxModel.id).where(ObjectMonitorOutboxModel.event_id == event.event_id)).scalar_one_or_none()
            if exists is not None:
                return
            session.add(ObjectMonitorOutboxModel(event_id=event.event_id, payload=payload, source=source, status="pending"))
            session.commit()

    def claim_pending(self, limit: int = 100) -> List[ObjectChangeEvent]:
        """Claim and mark pending events as published, returning decoded payloads."""
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
    """Convert datetime-like values from database payloads into datetime."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _to_version_record(row: MonitorVersionModel) -> MonitorVersionRecord:
    """Map ORM monitor version row to API contract object."""
    return MonitorVersionRecord(
        monitor_id=row.monitor_id,
        monitor_version=row.monitor_version,
        plan_hash=row.plan_hash,
        status=MonitorVersionStatus(row.status),
        command_id=row.command_id,
        operator=row.operator,
        created_at=row.created_at,
        published_at=row.published_at,
        rollback_from_version=row.rollback_from_version,
    )


def _require_version(session: Session, monitor_id: str, monitor_version: int) -> MonitorVersionModel:
    """Load a monitor version row or raise a descriptive KeyError."""
    row = session.execute(
        select(MonitorVersionModel).where(
            and_(MonitorVersionModel.monitor_id == monitor_id, MonitorVersionModel.monitor_version == monitor_version)
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError(f"monitor version not found: {monitor_id}#{monitor_version}")
    return row
