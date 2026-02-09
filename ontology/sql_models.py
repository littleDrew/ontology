from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Column, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ActionExecutionModel(Base):
    __tablename__ = "action_executions"
    __table_args__ = (
        Index("ix_action_executions_status", "status"),
        Index("ix_action_executions_action_name", "action_name"),
        Index("ix_action_executions_submitter", "submitter"),
        Index("ix_action_executions_submitted_at", "submitted_at"),
    )

    id = Column(String(64), primary_key=True)
    action_name = Column(String(255), nullable=False)
    submitter = Column(String(255), nullable=False)
    status = Column(String(32), nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    input_payload = Column(JSON, nullable=False)
    output_payload = Column(JSON)
    ontology_edit = Column(JSON)
    compensation_edit = Column(JSON)
    error = Column(Text)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)


class ActionDefinitionModel(Base):
    __tablename__ = "action_definitions"
    __table_args__ = (
        Index("ix_action_definitions_name", "name"),
        Index("ix_action_definitions_name_version", "name", "version", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)
    function_name = Column(String(255), nullable=False)
    input_schema = Column(JSON, nullable=False)
    output_schema = Column(JSON, nullable=False)
    active = Column(Integer, nullable=False, default=1)


class FunctionDefinitionModel(Base):
    __tablename__ = "function_definitions"
    __table_args__ = (
        Index("ix_function_definitions_name", "name"),
        Index("ix_function_definitions_name_version", "name", "version", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    version = Column(Integer, nullable=False)
    runtime = Column(String(64), nullable=False)
    code_ref = Column(String(255), nullable=False)
    input_schema = Column(JSON, nullable=False)
    output_schema = Column(JSON, nullable=False)


class ActionStateModel(Base):
    __tablename__ = "action_states"
    __table_args__ = (
        Index("ix_action_states_status", "status"),
        Index("ix_action_states_created_at", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    intent_payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class ActionLogModel(Base):
    __tablename__ = "action_logs"
    __table_args__ = (Index("ix_action_logs_execution_id", "execution_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(64), nullable=False)
    event_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class ActionRevertModel(Base):
    __tablename__ = "action_reverts"
    __table_args__ = (Index("ix_action_reverts_original_execution_id", "original_execution_id"),)

    id = Column(String(64), primary_key=True)
    original_execution_id = Column(String(64), nullable=False)
    revert_execution_id = Column(String(64), nullable=False)
    status = Column(String(32), nullable=False)
    reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class OutboxModel(Base):
    __tablename__ = "side_effect_outbox"
    __table_args__ = (
        Index("ix_side_effect_outbox_status", "status"),
        Index("ix_side_effect_outbox_execution_id", "execution_id"),
        Index("ix_side_effect_outbox_created_at", "created_at"),
    )

    id = Column(String(64), primary_key=True)
    execution_id = Column(String(64), nullable=False)
    effect_type = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="pending")
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    next_attempt_at = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class NotificationLogModel(Base):
    __tablename__ = "notification_logs"
    __table_args__ = (Index("ix_notification_logs_execution_id", "execution_id"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(String(64), nullable=False)
    channel = Column(String(64), nullable=False)
    subject = Column(String(255), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
