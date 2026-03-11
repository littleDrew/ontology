from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, create_engine, select, update
from sqlalchemy.orm import Session

from ontology.object_monitor.define.api.contracts import MonitorArtifact, MonitorDefinition, MonitorVersionRecord, MonitorVersionStatus
from ontology.object_monitor.define.compiler.dsl import ValidationContext, parse_monitor_definition, validate_monitor_definition
from ontology.object_monitor.define.compiler.service import build_monitor_artifact
from ontology.object_monitor.storage.sql_models import Base, MonitorVersionModel


class SqlAlchemyMonitorReleaseService:
    """SQLAlchemy implementation of monitor definition/release workflow."""

    def __init__(self, db_url: str) -> None:
        self._engine = create_engine(db_url)
        Base.metadata.create_all(self._engine)

    def create_definition(
        self,
        payload: dict[str, Any],
        *,
        available_fields: list[str],
        operator: str,
        limits: dict[str, Any] | None = None,
        now: datetime | None = None,
    ) -> MonitorVersionRecord:
        parsed = parse_monitor_definition(payload)
        validate_monitor_definition(parsed, ValidationContext(available_fields=available_fields))
        now = now or datetime.utcnow()

        with Session(self._engine) as session:
            latest = session.execute(
                select(MonitorVersionModel.monitor_version)
                .where(MonitorVersionModel.monitor_id == parsed.general.name)
                .order_by(MonitorVersionModel.monitor_version.desc())
                .limit(1)
            ).scalar_one_or_none()
            next_version = 1 if latest is None else latest + 1
            artifact = build_monitor_artifact(parsed, monitor_version=next_version, limits=limits)

            row = MonitorVersionModel(
                monitor_id=parsed.general.name,
                monitor_version=next_version,
                plan_hash=artifact.plan_hash,
                status=MonitorVersionStatus.draft.value,
                command_id=f"cmd-{uuid4()}",
                operator=operator,
                definition_json=asdict(parsed),
                artifact_json=asdict(artifact),
                created_at=now,
            )
            session.add(row)
            session.commit()
            return _to_version_record(row)

    def publish(self, monitor_id: str, monitor_version: int, *, operator: str, now: datetime | None = None) -> MonitorVersionRecord:
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
        with Session(self._engine) as session:
            row = session.execute(
                select(MonitorVersionModel)
                .where(and_(MonitorVersionModel.monitor_id == monitor_id, MonitorVersionModel.status == MonitorVersionStatus.active.value))
                .order_by(MonitorVersionModel.monitor_version.desc())
                .limit(1)
            ).scalar_one()
            return MonitorArtifact(**row.artifact_json)


def _to_version_record(row: MonitorVersionModel) -> MonitorVersionRecord:
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
    row = session.execute(
        select(MonitorVersionModel).where(
            and_(MonitorVersionModel.monitor_id == monitor_id, MonitorVersionModel.monitor_version == monitor_version)
        )
    ).scalar_one_or_none()
    if row is None:
        raise KeyError(f"monitor version not found: {monitor_id}#{monitor_version}")
    return row


__all__ = ["SqlAlchemyMonitorReleaseService"]
