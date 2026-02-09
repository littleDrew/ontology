from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Protocol, Tuple

from .action_models import (
    ActionDefinition,
    ActionExecution,
    ActionLog,
    ActionRevert,
    ActionState,
    ActionStateStatus,
    FunctionDefinition,
    NotificationLog,
    SideEffectOutbox,
)


class ActionRepository(Protocol):
    def add_action(self, definition: ActionDefinition) -> None: ...

    def add_function(self, definition: FunctionDefinition) -> None: ...

    def get_action(self, name: str, version: int | None = None) -> ActionDefinition | None: ...

    def get_function(self, name: str, version: int | None = None) -> FunctionDefinition | None: ...

    def get_execution(self, execution_id: str) -> ActionExecution | None: ...

    def add_execution(self, execution: ActionExecution) -> None: ...

    def update_execution(self, execution: ActionExecution) -> None: ...

    def add_log(self, log: ActionLog) -> None: ...

    def add_revert(self, revert: ActionRevert) -> None: ...

    def add_notification_log(self, log: NotificationLog) -> None: ...

    def add_outbox(self, entry: SideEffectOutbox) -> None: ...

    def update_outbox(self, entry: SideEffectOutbox) -> None: ...

    def claim_pending_outbox(self, limit: int = 100) -> List[SideEffectOutbox]: ...

    def add_action_state(self, state: ActionState) -> None: ...

    def update_action_state(self, state: ActionState) -> None: ...

    def confirm_action_state(
        self,
        state: ActionState,
        outbox_entries: List[SideEffectOutbox],
    ) -> None: ...

    def list_stale_action_states(self, cutoff_seconds: int) -> List[ActionState]: ...


@dataclass
class InMemoryActionRepository:
    actions: Dict[Tuple[str, int], ActionDefinition] = field(default_factory=dict)
    functions: Dict[Tuple[str, int], FunctionDefinition] = field(default_factory=dict)
    executions: Dict[str, ActionExecution] = field(default_factory=dict)
    logs: List[ActionLog] = field(default_factory=list)
    reverts: List[ActionRevert] = field(default_factory=list)
    notification_logs: List[NotificationLog] = field(default_factory=list)
    outbox: Dict[str, SideEffectOutbox] = field(default_factory=dict)
    action_states: Dict[str, ActionState] = field(default_factory=dict)

    def add_action(self, definition: ActionDefinition) -> None:
        self.actions[(definition.name, definition.version)] = definition

    def add_function(self, definition: FunctionDefinition) -> None:
        self.functions[(definition.name, definition.version)] = definition

    def get_action(self, name: str, version: int | None = None) -> ActionDefinition | None:
        if version is not None:
            return self.actions.get((name, version))
        versions = [ver for (action_name, ver) in self.actions.keys() if action_name == name]
        if not versions:
            return None
        return self.actions.get((name, max(versions)))

    def get_function(self, name: str, version: int | None = None) -> FunctionDefinition | None:
        if version is not None:
            return self.functions.get((name, version))
        versions = [ver for (fn_name, ver) in self.functions.keys() if fn_name == name]
        if not versions:
            return None
        return self.functions.get((name, max(versions)))

    def add_execution(self, execution: ActionExecution) -> None:
        self.executions[execution.execution_id] = execution

    def get_execution(self, execution_id: str) -> ActionExecution | None:
        return self.executions.get(execution_id)

    def update_execution(self, execution: ActionExecution) -> None:
        self.executions[execution.execution_id] = execution

    def add_log(self, log: ActionLog) -> None:
        self.logs.append(log)

    def add_revert(self, revert: ActionRevert) -> None:
        self.reverts.append(revert)

    def add_notification_log(self, log: NotificationLog) -> None:
        self.notification_logs.append(log)

    def add_outbox(self, entry: SideEffectOutbox) -> None:
        self.outbox[entry.outbox_id] = entry

    def update_outbox(self, entry: SideEffectOutbox) -> None:
        self.outbox[entry.outbox_id] = entry

    def claim_pending_outbox(self, limit: int = 100) -> List[SideEffectOutbox]:
        claimed = []
        for entry in sorted(self.outbox.values(), key=lambda item: item.created_at):
            if entry.status != "pending":
                continue
            if entry.next_attempt_at > datetime.utcnow():
                continue
            entry.status = "in_progress"
            claimed.append(entry)
            if len(claimed) >= limit:
                break
        return claimed

    def add_action_state(self, state: ActionState) -> None:
        self.action_states[state.action_id] = state

    def update_action_state(self, state: ActionState) -> None:
        self.action_states[state.action_id] = state

    def confirm_action_state(
        self,
        state: ActionState,
        outbox_entries: List[SideEffectOutbox],
    ) -> None:
        self.update_action_state(state)
        for entry in outbox_entries:
            self.add_outbox(entry)

    def list_stale_action_states(self, cutoff_seconds: int) -> List[ActionState]:
        cutoff = datetime.utcnow().timestamp() - cutoff_seconds
        return [
            state
            for state in self.action_states.values()
            if state.status == ActionStateStatus.pending and state.created_at.timestamp() <= cutoff
        ]
