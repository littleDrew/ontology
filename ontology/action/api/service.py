from __future__ import annotations

"""Action orchestration service and phase-1 runtime behaviors.

This module contains the core execution path for stage-1:
submit -> execute function -> validate/apply edits -> persist execution logs.
"""

from dataclasses import dataclass
from datetime import timedelta
import uuid
from typing import Any, Callable, Dict, List, Optional

from .domain_models import (
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
from ..storage.repository import ActionRepository
from ontology.instance.api.service import InstanceService
from ..storage.edits import ObjectLocator, edit_to_dict
from ..execution.notifications import NotificationDispatcher, NotificationMessage, WebhookDispatcher
from ..execution.runtime import ActionRunner
from ..config import ActionFeatureFlags
from ..utils import now_utc


SideEffectHandler = Callable[[Dict[str, Any]], None]


def _redact_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    redacted: Dict[str, Any] = {}
    for key, value in payload.items():
        lowered = key.lower()
        if any(token in lowered for token in ("password", "secret", "token", "card", "ssn")):
            redacted[key] = "***"
        else:
            redacted[key] = value
    return redacted


@dataclass
class SideEffect:
    effect_type: str
    payload: Dict[str, Any]


class SideEffectRegistry:
    """Registry for stage-2 side-effect handlers (disabled by default in phase-1)."""
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
    """Best-effort outbox worker for stage-2 side effects."""
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
                    entry.next_attempt_at = now_utc() + timedelta(seconds=backoff_seconds)
                entry.updated_at = now_utc()
                self._repository.update_outbox(entry)
                continue
            entry.status = "completed"
            entry.next_attempt_at = now_utc()
            entry.updated_at = now_utc()
            self._repository.update_outbox(entry)


class ActionReconciler:
    """Backfill helper for action_state/outbox consistency windows."""
    def __init__(self, repository: ActionRepository, apply_engine: InstanceService) -> None:
        self._repository = repository
        self._apply_engine = apply_engine

    def reconcile(self, cutoff_seconds: int = 60) -> None:
        for state in self._repository.list_stale_action_states(cutoff_seconds):
            if self._apply_engine.store.has_action_applied(state.action_id, state.intent_payload.get("edits")):
                state.status = ActionStateStatus.succeeded
                state.updated_at = now_utc()
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
                state.updated_at = now_utc()
                self._repository.update_action_state(state)


class ActionService:
    """Primary action application service for phase-1 core flow."""
    def __init__(
        self,
        repository: ActionRepository,
        runner: ActionRunner,
        apply_engine: InstanceService,
        feature_flags: ActionFeatureFlags | None = None,
    ) -> None:
        self._repository = repository
        self._runner = runner
        self._apply_engine = apply_engine
        self._feature_flags = feature_flags or ActionFeatureFlags()

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
            submitted_at=now_utc(),
            input_payload=input_payload,
        )
        self._repository.add_execution(execution)
        self._repository.add_log(
            ActionLog(
                execution_id=execution.execution_id,
                event_type="submitted",
                payload=input_payload,
                created_at=now_utc(),
            )
        )
        return execution

    def apply(
        self,
        action_name: str,
        submitter: str,
        input_payload: Dict[str, Any],
        version: int | None = None,
        input_instance_locators: Dict[str, Dict[str, Any]] | None = None,
    ) -> ActionExecution:
        definition = self._repository.get_action(action_name, version)
        if definition is None:
            raise ValueError("Action definition not found")

        function = self._runner.resolve(definition.function_name)
        if function is None:
            raise ValueError(f"Function '{definition.function_name}' is not registered")

        execution = self.submit(definition=definition, submitter=submitter, input_payload=input_payload)
        resolved_instances = self._resolve_input_instances(input_instance_locators or {})
        return self.execute(
            execution=execution,
            definition=definition,
            function=function,
            input_instances=resolved_instances,
        )

    def _resolve_input_instances(
        self,
        input_instance_locators: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Resolve user-provided input instance locators to graph instances.

        The payload shape is: {alias: {object_type, primary_key, version?}}.
        """
        resolved: Dict[str, Any] = {}
        for alias, locator in input_instance_locators.items():
            object_type = locator.get("object_type")
            primary_key = locator.get("primary_key")
            if not object_type or not primary_key:
                raise ValueError(f"Invalid input instance locator for '{alias}'")
            version = locator.get("version")
            object_locator = ObjectLocator(object_type=object_type, primary_key=primary_key, version=version)
            instance = self._apply_engine.get_object(object_locator)
            if instance is None:
                raise ValueError(f"Input instance not found for '{alias}'")
            resolved[alias] = instance
        return resolved

    def execute(
        self,
        execution: ActionExecution,
        definition: ActionDefinition,
        function: Callable[..., Any],
        input_instances: Dict[str, Any],
        side_effects: Optional[List[SideEffect]] = None,
    ) -> ActionExecution:
        """Execute one action attempt end-to-end and persist lifecycle logs."""
        execution.status = ActionStatus.validating
        execution.started_at = now_utc()
        self._repository.update_execution(execution)
        self._repository.add_log(
            ActionLog(
                execution_id=execution.execution_id,
                event_type="execution_started",
                payload={},
                created_at=now_utc(),
            )
        )
        completed_steps = []
        action_state: ActionState | None = None
        current_stage = "validating"
        try:
            # 1) Function execution stage
            current_stage = "executing"
            execution.status = ActionStatus.executing
            self._repository.update_execution(execution)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="function_started",
                    payload={"function_name": definition.function_name},
                    created_at=now_utc(),
                )
            )
            result = self._runner.execute(function, input_instances, params=execution.input_payload)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="function_finished",
                    payload={"function_name": definition.function_name},
                    created_at=now_utc(),
                )
            )
            # 2) Persist captured edits to instance store
            current_stage = "applying"
            execution.status = ActionStatus.applying
            self._repository.update_execution(execution)
            execution.output_payload = {"result": result["result"]}
            execution.ontology_edit = result["edits"]
            intent_payload = {
                "edits": edit_to_dict(result["edits"]),
                "side_effects": [
                    {"effect_type": effect.effect_type, "payload": effect.payload} for effect in ((side_effects or []) if self._feature_flags.side_effects_enabled else [])
                ],
            }
            action_state = ActionState(
                action_id=execution.execution_id,
                execution_id=execution.execution_id,
                status=ActionStateStatus.pending,
                intent_payload=intent_payload,
                created_at=now_utc(),
                updated_at=now_utc(),
            )
            self._repository.add_action_state(action_state)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="apply_started",
                    payload={"edit_count": len(result["edits"].edits)},
                    created_at=now_utc(),
                )
            )
            apply_result = self._apply_engine.apply(result["edits"], action_id=execution.execution_id)
            if not apply_result.applied:
                self._repository.add_log(
                    ActionLog(
                        execution_id=execution.execution_id,
                        event_type="apply_failed",
                        payload={
                            "failed_stage": "applying",
                            "error_code": "E_APPLY_INTERNAL",
                            "retryable": False,
                            "redacted_context": _redact_payload(execution.input_payload),
                            "message": apply_result.error or "Apply failed",
                        },
                        created_at=now_utc(),
                    )
                )
                raise ValueError(apply_result.error or "Apply failed")
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="apply_succeeded",
                    payload={"edit_count": len(result["edits"].edits)},
                    created_at=now_utc(),
                )
            )
            outbox_entries = []
            if self._feature_flags.side_effects_enabled and side_effects:
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
                action_state.updated_at = now_utc()
                self._repository.confirm_action_state(action_state, outbox_entries)
            if self._feature_flags.saga_enabled:
                for step in definition.saga_steps:
                    completed_steps.append(step)
                    try:
                        step.action(input_instances, execution.input_payload)
                    except Exception:
                        raise
            # 3) Mark terminal success after apply + optional saga path
            execution.status = ActionStatus.succeeded
        except Exception as exc:  # noqa: BLE001
            execution.status = ActionStatus.failed
            execution.error = str(exc)
            if action_state:
                action_state.status = ActionStateStatus.failed
                action_state.updated_at = now_utc()
                self._repository.update_action_state(action_state)
            if self._feature_flags.saga_enabled:
                for step in reversed(completed_steps):
                    if step.compensation:
                        step.compensation(input_instances, execution.input_payload)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="execution_failed",
                    payload={
                        "failed_stage": current_stage,
                        "error_code": "E_ACTION_EXECUTION",
                        "retryable": False,
                        "redacted_context": _redact_payload(execution.input_payload),
                        "message": str(exc),
                    },
                    created_at=now_utc(),
                )
            )
            if self._feature_flags.revert_enabled and definition.compensation_fn:
                compensation = definition.compensation_fn(input_instances, execution.input_payload)
                execution.compensation_edit = compensation
                compensation_result = self._apply_engine.apply(compensation, action_id=execution.execution_id)
                if compensation_result.applied:
                    execution.status = ActionStatus.reverted
        finally:
            execution.finished_at = now_utc()
            self._repository.update_execution(execution)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="finished",
                    payload={"status": execution.status.value},
                    created_at=now_utc(),
                )
            )
        return execution

    def revert(self, execution: ActionExecution) -> ActionExecution:
        if not self._feature_flags.revert_enabled:
            raise ValueError("Revert feature is disabled")
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
                created_at=now_utc(),
            )
        )
        self._repository.add_log(
            ActionLog(
                execution_id=execution.execution_id,
                event_type="reverted",
                payload={},
                created_at=now_utc(),
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
                created_at=now_utc(),
            )
        )


class WebhookEffectHandler:
    def __init__(self, dispatcher: WebhookDispatcher) -> None:
        self._dispatcher = dispatcher

    def __call__(self, payload: Dict[str, Any]) -> None:
        status = self._dispatcher.post(payload["url"], payload.get("body", {}))
        if status >= 400:
            raise ValueError(f"Webhook failed with status {status}")
