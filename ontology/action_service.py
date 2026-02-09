from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import uuid
from typing import Any, Callable, Dict, List, Optional

from .action_models import (
    ActionDefinition,
    ActionExecution,
    ActionLog,
    ActionRevert,
    ActionState,
    ActionStateStatus,
    ActionStatus,
    NotificationLog,
    SideEffectOutbox,
)
from .action_repository import ActionRepository
from .apply import DataFunnelService
from .edits import edit_to_dict
from .notifications import NotificationDispatcher, NotificationMessage, WebhookDispatcher
from .runtime import ActionRunner


SideEffectHandler = Callable[[Dict[str, Any]], None]


@dataclass
class SideEffect:
    effect_type: str
    payload: Dict[str, Any]


class SideEffectRegistry:
    def __init__(self) -> None:
        self._handlers: Dict[str, SideEffectHandler] = {}

    def register(self, effect_type: str, handler: SideEffectHandler) -> None:
        self._handlers[effect_type] = handler

    def handle(self, effect_type: str, payload: Dict[str, Any]) -> None:
        handler = self._handlers.get(effect_type)
        if handler is None:
            raise ValueError(f"Missing side effect handler: {effect_type}")
        handler(payload)


class SideEffectWorker:
    def __init__(self, repository: ActionRepository, registry: SideEffectRegistry) -> None:
        self._repository = repository
        self._registry = registry

    def drain(self) -> None:
        for entry in self._repository.claim_pending_outbox():
            try:
                self._registry.handle(entry.effect_type, entry.payload)
            except Exception:  # noqa: BLE001
                entry.retry_count += 1
                if entry.retry_count >= entry.max_retries:
                    entry.status = "dead_letter"
                else:
                    backoff_seconds = 2 ** entry.retry_count
                    entry.status = "pending"
                    entry.next_attempt_at = datetime.utcnow() + timedelta(seconds=backoff_seconds)
                entry.updated_at = datetime.utcnow()
                self._repository.update_outbox(entry)
                continue
            entry.status = "completed"
            entry.next_attempt_at = datetime.utcnow()
            entry.updated_at = datetime.utcnow()
            self._repository.update_outbox(entry)


class ActionReconciler:
    def __init__(self, repository: ActionRepository, apply_engine: DataFunnelService) -> None:
        self._repository = repository
        self._apply_engine = apply_engine

    def reconcile(self, cutoff_seconds: int = 60) -> None:
        for state in self._repository.list_stale_action_states(cutoff_seconds):
            if self._apply_engine.store.has_action_applied(state.action_id, state.intent_payload.get("edits")):
                state.status = ActionStateStatus.succeeded
                state.updated_at = datetime.utcnow()
                outbox_entries = []
                for payload in state.intent_payload.get("side_effects", []):
                    outbox_entries.append(
                        SideEffectOutbox(
                            outbox_id=str(uuid.uuid4()),
                            execution_id=state.execution_id,
                            effect_type=payload.get("effect_type", "unknown"),
                            payload=payload.get("payload", {}),
                        )
                    )
                self._repository.confirm_action_state(state, outbox_entries)
            else:
                state.status = ActionStateStatus.failed
                state.updated_at = datetime.utcnow()
                self._repository.update_action_state(state)


class ActionService:
    def __init__(
        self,
        repository: ActionRepository,
        runner: ActionRunner,
        apply_engine: DataFunnelService,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._apply_engine = apply_engine

    def submit(
        self,
        definition: ActionDefinition,
        submitter: str,
        input_payload: Dict[str, Any],
    ) -> ActionExecution:
        if not definition.active:
            raise ValueError("Action is inactive")
        if definition.submission_criteria and not definition.submission_criteria(input_payload):
            raise ValueError("Submission criteria not satisfied")
        execution = ActionExecution(
            execution_id=str(uuid.uuid4()),
            action_name=definition.name,
            submitter=submitter,
            status=ActionStatus.queued,
            submitted_at=datetime.utcnow(),
            input_payload=input_payload,
        )
        self._repository.add_execution(execution)
        self._repository.add_log(
            ActionLog(
                execution_id=execution.execution_id,
                event_type="submitted",
                payload=input_payload,
                created_at=datetime.utcnow(),
            )
        )
        return execution

    def execute(
        self,
        execution: ActionExecution,
        definition: ActionDefinition,
        function: Callable[..., Any],
        input_instances: Dict[str, Any],
        side_effects: Optional[List[SideEffect]] = None,
    ) -> ActionExecution:
        execution.status = ActionStatus.running
        execution.started_at = datetime.utcnow()
        self._repository.update_execution(execution)
        self._repository.add_log(
            ActionLog(
                execution_id=execution.execution_id,
                event_type="started",
                payload={},
                created_at=datetime.utcnow(),
            )
        )
        completed_steps = []
        action_state: ActionState | None = None
        try:
            result = self._runner.execute(function, input_instances, params=execution.input_payload)
            execution.output_payload = {"result": result["result"]}
            execution.ontology_edit = result["edits"]
            intent_payload = {
                "edits": edit_to_dict(result["edits"]),
                "side_effects": [
                    {"effect_type": effect.effect_type, "payload": effect.payload} for effect in (side_effects or [])
                ],
            }
            action_state = ActionState(
                action_id=execution.execution_id,
                execution_id=execution.execution_id,
                status=ActionStateStatus.pending,
                intent_payload=intent_payload,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            self._repository.add_action_state(action_state)
            apply_result = self._apply_engine.apply(result["edits"], action_id=execution.execution_id)
            if not apply_result.applied:
                raise ValueError(apply_result.error or "Apply failed")
            outbox_entries = []
            if side_effects:
                for effect in side_effects:
                    outbox_entries.append(
                        SideEffectOutbox(
                            outbox_id=str(uuid.uuid4()),
                            execution_id=execution.execution_id,
                            effect_type=effect.effect_type,
                            payload=effect.payload,
                        )
                    )
            if action_state:
                action_state.status = ActionStateStatus.succeeded
                action_state.updated_at = datetime.utcnow()
                self._repository.confirm_action_state(action_state, outbox_entries)
            for step in definition.saga_steps:
                completed_steps.append(step)
                try:
                    step.action(input_instances, execution.input_payload)
                except Exception:
                    raise
            execution.status = ActionStatus.succeeded
        except Exception as exc:  # noqa: BLE001
            execution.status = ActionStatus.failed
            execution.error = str(exc)
            if action_state:
                action_state.status = ActionStateStatus.failed
                action_state.updated_at = datetime.utcnow()
                self._repository.update_action_state(action_state)
            for step in reversed(completed_steps):
                if step.compensation:
                    step.compensation(input_instances, execution.input_payload)
            if definition.compensation_fn:
                compensation = definition.compensation_fn(input_instances, execution.input_payload)
                execution.compensation_edit = compensation
                compensation_result = self._apply_engine.apply(compensation, action_id=execution.execution_id)
                if compensation_result.applied:
                    execution.status = ActionStatus.reverted
        finally:
            execution.finished_at = datetime.utcnow()
            self._repository.update_execution(execution)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="finished",
                    payload={"status": execution.status.value},
                    created_at=datetime.utcnow(),
                )
            )
        return execution

    def revert(self, execution: ActionExecution) -> ActionExecution:
        if execution.compensation_edit is None:
            raise ValueError("No compensation edit available for revert")
        revert_execution_id = str(uuid.uuid4())
        result = self._apply_engine.apply(execution.compensation_edit, action_id=revert_execution_id)
        if not result.applied:
            raise ValueError(result.error or "Revert failed")
        execution.status = ActionStatus.reverted
        self._repository.update_execution(execution)
        self._repository.add_revert(
            ActionRevert(
                revert_id=str(uuid.uuid4()),
                original_execution_id=execution.execution_id,
                revert_execution_id=revert_execution_id,
                status=ActionStatus.reverted,
                created_at=datetime.utcnow(),
            )
        )
        self._repository.add_log(
            ActionLog(
                execution_id=execution.execution_id,
                event_type="reverted",
                payload={},
                created_at=datetime.utcnow(),
            )
        )
        return execution


class NotificationEffectHandler:
    def __init__(self, dispatcher: NotificationDispatcher, repository: ActionRepository) -> None:
        self._dispatcher = dispatcher
        self._repository = repository

    def __call__(self, payload: Dict[str, Any]) -> None:
        message = NotificationMessage(
            channel=payload["channel"],
            subject=payload["subject"],
            body=payload["body"],
            metadata=payload.get("metadata"),
        )
        self._dispatcher.send(message)
        self._repository.add_notification_log(
            NotificationLog(
                execution_id=payload.get("execution_id", "unknown"),
                channel=message.channel,
                subject=message.subject,
                payload={"body": message.body, "metadata": message.metadata},
                created_at=datetime.utcnow(),
            )
        )


class WebhookEffectHandler:
    def __init__(self, dispatcher: WebhookDispatcher) -> None:
        self._dispatcher = dispatcher

    def __call__(self, payload: Dict[str, Any]) -> None:
        status = self._dispatcher.post(payload["url"], payload.get("body", {}))
        if status >= 400:
            raise ValueError(f"Webhook failed with status {status}")
