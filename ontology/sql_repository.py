from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from .action_models import (
    ActionExecution,
    ActionLog,
    ActionRevert,
    ActionState,
    ActionStateStatus,
    ActionDefinition,
    FunctionDefinition,
    ActionStatus,
    NotificationLog,
    SideEffectOutbox,
)
from .edits import edit_to_dict
from .sql_models import (
    ActionExecutionModel,
    ActionDefinitionModel,
    ActionLogModel,
    ActionRevertModel,
    ActionStateModel,
    FunctionDefinitionModel,
    NotificationLogModel,
    OutboxModel,
    Base,
)


class SqlActionRepository:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)
        Base.metadata.create_all(self._engine)

    def add_execution(self, execution: ActionExecution) -> None:
        with Session(self._engine) as session:
            session.add(
                ActionExecutionModel(
                    id=execution.execution_id,
                    action_name=execution.action_name,
                    submitter=execution.submitter,
                    status=execution.status.value,
                    submitted_at=execution.submitted_at,
                    input_payload=execution.input_payload,
                    output_payload=execution.output_payload,
                    ontology_edit=self._serialize_edit(execution.ontology_edit),
                    compensation_edit=self._serialize_edit(execution.compensation_edit),
                    error=execution.error,
                    started_at=execution.started_at,
                    finished_at=execution.finished_at,
                )
            )
            session.commit()

    def get_execution(self, execution_id: str) -> ActionExecution | None:
        with Session(self._engine) as session:
            row = session.get(ActionExecutionModel, execution_id)
        if row is None:
            return None
        return ActionExecution(
            execution_id=row.id,
            action_name=row.action_name,
            submitter=row.submitter,
            status=ActionStatus(row.status),
            submitted_at=row.submitted_at,
            input_payload=row.input_payload,
            output_payload=row.output_payload or {},
            ontology_edit=None,
            compensation_edit=None,
            error=row.error,
            started_at=row.started_at,
            finished_at=row.finished_at,
        )

    def add_action(self, definition: ActionDefinition) -> None:
        with Session(self._engine) as session:
            session.add(
                ActionDefinitionModel(
                    name=definition.name,
                    version=definition.version,
                    description=definition.description,
                    function_name=definition.function_name,
                    input_schema=definition.input_schema,
                    output_schema=definition.output_schema,
                    active=1 if definition.active else 0,
                )
            )
            session.commit()

    def add_function(self, definition: FunctionDefinition) -> None:
        with Session(self._engine) as session:
            session.add(
                FunctionDefinitionModel(
                    name=definition.name,
                    version=definition.version,
                    runtime=definition.runtime,
                    code_ref=definition.code_ref,
                    input_schema=definition.input_schema,
                    output_schema=definition.output_schema,
                )
            )
            session.commit()

    def get_action(self, name: str, version: int | None = None) -> ActionDefinition | None:
        with Session(self._engine) as session:
            if version is None:
                stmt = (
                    select(ActionDefinitionModel)
                    .where(ActionDefinitionModel.name == name)
                    .order_by(ActionDefinitionModel.version.desc())
                    .limit(1)
                )
            else:
                stmt = select(ActionDefinitionModel).where(
                    ActionDefinitionModel.name == name,
                    ActionDefinitionModel.version == version,
                )
            row = session.execute(stmt).scalars().first()
        if row is None:
            return None
        return ActionDefinition(
            name=row.name,
            description=row.description,
            function_name=row.function_name,
            input_schema=row.input_schema,
            output_schema=row.output_schema,
            version=row.version,
            active=bool(row.active),
        )

    def get_function(self, name: str, version: int | None = None) -> FunctionDefinition | None:
        with Session(self._engine) as session:
            if version is None:
                stmt = (
                    select(FunctionDefinitionModel)
                    .where(FunctionDefinitionModel.name == name)
                    .order_by(FunctionDefinitionModel.version.desc())
                    .limit(1)
                )
            else:
                stmt = select(FunctionDefinitionModel).where(
                    FunctionDefinitionModel.name == name,
                    FunctionDefinitionModel.version == version,
                )
            row = session.execute(stmt).scalars().first()
        if row is None:
            return None
        return FunctionDefinition(
            name=row.name,
            runtime=row.runtime,
            code_ref=row.code_ref,
            input_schema=row.input_schema,
            output_schema=row.output_schema,
            version=row.version,
        )

    def update_execution(self, execution: ActionExecution) -> None:
        with Session(self._engine) as session:
            stmt = (
                update(ActionExecutionModel)
                .where(ActionExecutionModel.id == execution.execution_id)
                .values(
                    status=execution.status.value,
                    output_payload=execution.output_payload,
                    ontology_edit=self._serialize_edit(execution.ontology_edit),
                    compensation_edit=self._serialize_edit(execution.compensation_edit),
                    error=execution.error,
                    started_at=execution.started_at,
                    finished_at=execution.finished_at,
                )
            )
            session.execute(stmt)
            session.commit()

    def add_log(self, log: ActionLog) -> None:
        with Session(self._engine) as session:
            session.add(
                ActionLogModel(
                    execution_id=log.execution_id,
                    event_type=log.event_type,
                    payload=log.payload,
                    created_at=log.created_at,
                )
            )
            session.commit()

    def add_revert(self, revert: ActionRevert) -> None:
        with Session(self._engine) as session:
            session.add(
                ActionRevertModel(
                    id=revert.revert_id,
                    original_execution_id=revert.original_execution_id,
                    revert_execution_id=revert.revert_execution_id,
                    status=revert.status.value,
                    reason=revert.reason,
                    created_at=revert.created_at,
                )
            )
            session.commit()

    def add_notification_log(self, log: NotificationLog) -> None:
        with Session(self._engine) as session:
            session.add(
                NotificationLogModel(
                    execution_id=log.execution_id,
                    channel=log.channel,
                    subject=log.subject,
                    payload=log.payload,
                    created_at=log.created_at,
                )
            )
            session.commit()

    def add_outbox(self, entry: SideEffectOutbox) -> None:
        with Session(self._engine) as session:
            session.add(
                OutboxModel(
                    id=entry.outbox_id,
                    execution_id=entry.execution_id,
                    effect_type=entry.effect_type,
                    payload=entry.payload,
                    status=entry.status,
                    retry_count=entry.retry_count,
                    max_retries=entry.max_retries,
                    next_attempt_at=entry.next_attempt_at,
                    created_at=entry.created_at,
                    updated_at=entry.updated_at,
                )
            )
            session.commit()

    def update_outbox(self, entry: SideEffectOutbox) -> None:
        with Session(self._engine) as session:
            stmt = (
                update(OutboxModel)
                .where(OutboxModel.id == entry.outbox_id)
                .values(
                    status=entry.status,
                    retry_count=entry.retry_count,
                    max_retries=entry.max_retries,
                    next_attempt_at=entry.next_attempt_at,
                    updated_at=entry.updated_at,
                )
            )
            session.execute(stmt)
            session.commit()

    def claim_pending_outbox(self, limit: int = 100) -> list[SideEffectOutbox]:
        with Session(self._engine) as session:
            stmt = (
                select(OutboxModel)
                .where(OutboxModel.status == "pending")
                .where(OutboxModel.next_attempt_at <= datetime.utcnow())
                .order_by(OutboxModel.created_at)
                .limit(limit)
            )
            rows = session.execute(stmt).scalars().all()
            claimed: list[SideEffectOutbox] = []
            for row in rows:
                update_stmt = (
                    update(OutboxModel)
                    .where(OutboxModel.id == row.id, OutboxModel.status == "pending")
                    .values(status="in_progress", updated_at=datetime.utcnow())
                )
                result = session.execute(update_stmt)
                if result.rowcount:
                    claimed.append(
                        SideEffectOutbox(
                            outbox_id=row.id,
                            execution_id=row.execution_id,
                            effect_type=row.effect_type,
                            payload=row.payload,
                            status="in_progress",
                            retry_count=row.retry_count,
                            max_retries=row.max_retries,
                            next_attempt_at=row.next_attempt_at,
                            created_at=row.created_at,
                            updated_at=datetime.utcnow(),
                        )
                    )
            session.commit()
        return claimed

    def add_action_state(self, state: ActionState) -> None:
        with Session(self._engine) as session:
            session.add(
                ActionStateModel(
                    id=state.action_id,
                    execution_id=state.execution_id,
                    status=state.status.value,
                    intent_payload=state.intent_payload,
                    created_at=state.created_at,
                    updated_at=state.updated_at,
                )
            )
            session.commit()

    def update_action_state(self, state: ActionState) -> None:
        with Session(self._engine) as session:
            stmt = (
                update(ActionStateModel)
                .where(ActionStateModel.id == state.action_id)
                .values(
                    status=state.status.value,
                    intent_payload=state.intent_payload,
                    updated_at=state.updated_at,
                )
            )
            session.execute(stmt)
            session.commit()

    def confirm_action_state(
        self,
        state: ActionState,
        outbox_entries: list[SideEffectOutbox],
    ) -> None:
        with Session(self._engine) as session:
            stmt = (
                update(ActionStateModel)
                .where(ActionStateModel.id == state.action_id)
                .values(
                    status=state.status.value,
                    intent_payload=state.intent_payload,
                    updated_at=state.updated_at,
                )
            )
            session.execute(stmt)
            for entry in outbox_entries:
                session.add(
                    OutboxModel(
                        id=entry.outbox_id,
                        execution_id=entry.execution_id,
                        effect_type=entry.effect_type,
                        payload=entry.payload,
                        status=entry.status,
                        retry_count=entry.retry_count,
                        max_retries=entry.max_retries,
                        next_attempt_at=entry.next_attempt_at,
                        created_at=entry.created_at,
                        updated_at=entry.updated_at,
                    )
                )
            session.commit()

    def list_stale_action_states(self, cutoff_seconds: int) -> list[ActionState]:
        cutoff = datetime.utcnow() - timedelta(seconds=cutoff_seconds)
        with Session(self._engine) as session:
            stmt = (
                select(ActionStateModel)
                .where(ActionStateModel.status == ActionStateStatus.pending.value)
                .where(ActionStateModel.created_at <= cutoff)
                .order_by(ActionStateModel.created_at)
            )
            rows = session.execute(stmt).scalars().all()
        return [
            ActionState(
                action_id=row.id,
                execution_id=row.execution_id,
                status=ActionStateStatus(row.status),
                intent_payload=row.intent_payload,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in rows
        ]

    @staticmethod
    def _serialize_edit(edit: Any) -> Any:
        if edit is None:
            return None
        return edit_to_dict(edit)
