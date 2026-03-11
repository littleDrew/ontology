from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class MonitorVersionModel(Base):
    """ORM model storing monitor definition versions and release state."""

    __tablename__ = "monitor_versions"
    __table_args__ = (
        Index("ix_monitor_versions_monitor", "monitor_id"),
        Index("ux_monitor_versions_monitor_version", "monitor_id", "monitor_version", unique=True),
        Index("ix_monitor_versions_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    monitor_id = Column(String(255), nullable=False)
    monitor_version = Column(Integer, nullable=False)
    plan_hash = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False)
    command_id = Column(String(128), nullable=False)
    operator = Column(String(255), nullable=False)
    definition_json = Column(JSON, nullable=False)
    artifact_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    published_at = Column(DateTime, nullable=True)
    rollback_from_version = Column(Integer, nullable=True)


class MonitorEvaluationModel(Base):
    """ORM model for evaluation ledger records (idempotent per source version)."""

    __tablename__ = "monitor_evaluation"
    __table_args__ = (
        Index("ix_monitor_eval_tenant_monitor", "tenant_id", "monitor_id"),
        Index("ix_monitor_eval_event_time", "event_time"),
        Index("ux_monitor_eval_idempotency", "tenant_id", "monitor_id", "object_id", "source_version", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(128), nullable=False)
    monitor_id = Column(String(255), nullable=False)
    monitor_version = Column(Integer, nullable=False)
    object_id = Column(String(255), nullable=False)
    source_version = Column(Integer, nullable=False)
    result = Column(String(16), nullable=False)
    reason = Column(Text, nullable=False)
    snapshot_hash = Column(String(255), nullable=False)
    latency_ms = Column(Integer, nullable=False)
    event_time = Column(DateTime, nullable=False)


class MonitorActivityModel(Base):
    """ORM model for action activity tracking and current status."""

    __tablename__ = "monitor_activity"
    __table_args__ = (
        Index("ix_monitor_activity_tenant_status", "tenant_id", "status"),
        Index("ix_monitor_activity_monitor", "monitor_id"),
        Index("ix_monitor_activity_updated", "updated_at"),
    )

    activity_id = Column(String(64), primary_key=True)
    tenant_id = Column(String(128), nullable=False)
    monitor_id = Column(String(255), nullable=False)
    monitor_version = Column(Integer, nullable=False)
    object_id = Column(String(255), nullable=False)
    source_version = Column(Integer, nullable=False)
    status = Column(String(64), nullable=False)
    action_execution_id = Column(String(255), nullable=True)
    event_time = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class ActionDeliveryLogModel(Base):
    """ORM model for per-attempt action delivery logs."""

    __tablename__ = "action_delivery_log"
    __table_args__ = (
        Index("ix_delivery_log_activity", "activity_id"),
        Index("ix_delivery_log_created", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    activity_id = Column(String(64), nullable=False)
    delivery_attempt = Column(Integer, nullable=False)
    status = Column(String(64), nullable=False)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False)


class ObjectMonitorOutboxModel(Base):
    """ORM model for object monitor change outbox events."""

    __tablename__ = "object_monitor_change_outbox"
    __table_args__ = (
        Index("ix_objm_outbox_status", "status"),
        Index("ix_objm_outbox_created", "created_at"),
        Index("ux_objm_outbox_event", "event_id", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(128), nullable=False)
    payload = Column(JSON, nullable=False)
    source = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    published_at = Column(DateTime, nullable=True)


__all__ = [
    "ActionDeliveryLogModel",
    "Base",
    "MonitorActivityModel",
    "MonitorEvaluationModel",
    "MonitorVersionModel",
    "ObjectMonitorOutboxModel",
]
