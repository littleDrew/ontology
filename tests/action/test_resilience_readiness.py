"""W8-oriented resilience and readiness tests.

These tests focus on phase-1 operational confidence:
- lightweight throughput smoke check
- failure drill behavior
- SQL control-plane stale-scan correctness
"""

from __future__ import annotations

import time
from pathlib import Path

from ontology import (
    ActionDefinition,
    ActionExecution,
    ActionRunner,
    ActionService,
    ActionStatus,
    AddObjectEdit,
    DataFunnelService,
    InMemoryActionRepository,
    InMemoryGraphStore,
    ObjectLocator,
    TransactionEdit,
)
from ontology.action.execution.runtime import function_action
import pytest
from ontology.action.utils import now_utc


@function_action
def failing_action(loan, context, status: str) -> str:
    """Mutate proxy then fail to simulate execution-stage exception."""

    loan.status = status
    raise RuntimeError("simulated function failure")


def test_bulk_transaction_apply_smoke() -> None:
    """Apply a medium-size transaction as a lightweight pressure smoke test."""

    store = InMemoryGraphStore()
    service = DataFunnelService(store)

    edits = [AddObjectEdit("Loan", f"loan-{i}", {"status": "NEW", "amount": i}) for i in range(500)]
    tx = TransactionEdit(edits=edits)

    started = time.perf_counter()
    result = service.apply(tx)
    elapsed = time.perf_counter() - started

    assert result.applied is True
    assert len(store.list_objects("Loan", limit=1000)) == 500
    # generous threshold to avoid flaky failures in CI while still catching regressions.
    assert elapsed < 5.0


def test_fault_drill_function_exception_keeps_instance_unchanged() -> None:
    """Failure drill: execution exception must not partially apply captured mutations."""

    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-1", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    runner = ActionRunner()
    runner.register("failing_action", failing_action)
    service = ActionService(repo, runner, DataFunnelService(store))

    definition = ActionDefinition(
        name="FailingUpdate",
        description="Failure drill",
        function_name="failing_action",
        version=1,
    )
    repo.add_action(definition)

    execution = service.apply(
        action_name="FailingUpdate",
        submitter="ops-user",
        input_payload={"status": "APPROVED"},
        version=1,
        input_instance_locators={"loan": {"object_type": "Loan", "primary_key": "loan-1"}},
    )

    assert execution.status == ActionStatus.failed
    loan = store.get_object(ObjectLocator("Loan", "loan-1"))
    assert loan.properties["status"] == "PENDING"
    assert any(
        log.execution_id == execution.execution_id and log.event_type == "execution_failed"
        for log in repo.logs
    )


def test_sql_stale_scan_prefers_started_at(tmp_path: Path) -> None:
    """If started_at is recent, stale scan should not treat old submitted_at as stale."""

    pytest.importorskip("sqlalchemy")
    from ontology.action.storage.sql_repository import SqlActionRepository

    db_path = tmp_path / "w8_repair.db"
    repo = SqlActionRepository(f"sqlite:///{db_path}")

    exec_recent_start = ActionExecution(
        execution_id="exec-recent-start",
        action_name="A",
        submitter="u",
        status=ActionStatus.applying,
        submitted_at=now_utc().replace(year=2001),
        input_payload={},
        started_at=now_utc(),
    )
    repo.add_execution(exec_recent_start)

    exec_old_start = ActionExecution(
        execution_id="exec-old-start",
        action_name="A",
        submitter="u",
        status=ActionStatus.applying,
        submitted_at=now_utc().replace(year=2001),
        input_payload={},
        started_at=now_utc().replace(year=2001),
    )
    repo.add_execution(exec_old_start)

    stale = repo.list_stale_executions([ActionStatus.applying], cutoff_seconds=60)
    stale_ids = {item.execution_id for item in stale}

    assert "exec-old-start" in stale_ids
    assert "exec-recent-start" not in stale_ids
