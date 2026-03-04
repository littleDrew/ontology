from __future__ import annotations

"""Repair job implementation for stale control-plane executions.

Phase-1 guarantees graph apply atomicity. If control-plane state is left in
a non-terminal status, this job marks it failed and records audit evidence.
"""

from dataclasses import dataclass
from typing import List

from .domain_models import ActionExecution, ActionLog, ActionStatus
from ..storage.repository import ActionRepository
from ..utils import now_utc


REPAIRABLE_STATUSES = (
    ActionStatus.queued,
    ActionStatus.validating,
    ActionStatus.executing,
    ActionStatus.applying,
)


@dataclass
class RepairResult:
    scanned: int
    repaired: int
    repaired_execution_ids: List[str]


class ActionRepairJob:
    """Control-plane repair job for stale executions in non-terminal states."""

    def __init__(self, repository: ActionRepository) -> None:
        self._repository = repository

    def repair_stale_executions(self, cutoff_seconds: int = 300) -> RepairResult:
        """Repair executions stuck in non-terminal statuses."""
        stale = self._repository.list_stale_executions(REPAIRABLE_STATUSES, cutoff_seconds=cutoff_seconds)
        repaired_ids: list[str] = []
        for execution in stale:
            previous_status = execution.status
            execution.status = ActionStatus.failed
            execution.error = "E_REPAIR_STALE_EXECUTION: repaired stale execution in control plane"
            execution.finished_at = now_utc()
            self._repository.update_execution(execution)
            self._repository.add_log(
                ActionLog(
                    execution_id=execution.execution_id,
                    event_type="execution_repaired",
                    payload={
                        "previous_status": previous_status.value,
                        "status": execution.status.value,
                        "error_code": "E_REPAIR_STALE_EXECUTION",
                        "retryable": False,
                    },
                    created_at=now_utc(),
                )
            )
            repaired_ids.append(execution.execution_id)

        return RepairResult(
            scanned=len(stale),
            repaired=len(repaired_ids),
            repaired_execution_ids=repaired_ids,
        )
