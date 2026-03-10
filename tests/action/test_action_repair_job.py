from ontology import (
    ActionExecution,
    ActionLog,
    ActionRepairJob,
    ActionStatus,
    InMemoryActionRepository,
)
from ontology.action.utils import now_utc


def test_repair_job_marks_stale_executions_failed() -> None:
    repo = InMemoryActionRepository()
    stale = ActionExecution(
        execution_id="exec-stale",
        action_name="Approve",
        submitter="user-1",
        status=ActionStatus.applying,
        submitted_at=now_utc(),
        input_payload={"a": 1},
    )
    stale.started_at = stale.submitted_at.replace(year=stale.submitted_at.year - 1)
    # force stale by moving submitted_at far in past
    stale.submitted_at = stale.submitted_at.replace(year=stale.submitted_at.year - 1)
    repo.add_execution(stale)

    fresh = ActionExecution(
        execution_id="exec-fresh",
        action_name="Approve",
        submitter="user-1",
        status=ActionStatus.applying,
        submitted_at=now_utc(),
        input_payload={"a": 2},
    )
    repo.add_execution(fresh)

    result = ActionRepairJob(repo).repair_stale_executions(cutoff_seconds=60)

    assert result.scanned == 1
    assert result.repaired == 1
    assert result.repaired_execution_ids == ["exec-stale"]
    assert repo.executions["exec-stale"].status == ActionStatus.failed
    assert repo.executions["exec-fresh"].status == ActionStatus.applying

    repair_logs = [log for log in repo.logs if log.execution_id == "exec-stale" and log.event_type == "execution_repaired"]
    assert len(repair_logs) == 1
    assert repair_logs[0].payload["error_code"] == "E_REPAIR_STALE_EXECUTION"


def test_repair_job_does_not_touch_terminal_executions() -> None:
    repo = InMemoryActionRepository()
    done = ActionExecution(
        execution_id="exec-done",
        action_name="Approve",
        submitter="user-2",
        status=ActionStatus.succeeded,
        submitted_at=now_utc().replace(year=2000),
        input_payload={},
    )
    repo.add_execution(done)

    result = ActionRepairJob(repo).repair_stale_executions(cutoff_seconds=1)

    assert result.scanned == 0
    assert result.repaired == 0
    assert repo.executions["exec-done"].status == ActionStatus.succeeded
