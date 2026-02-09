import pytest

pytest.importorskip("sqlalchemy")

from datetime import datetime

from ontology import (
    ActionDefinition,
    ActionExecution,
    ActionLog,
    ActionRevert,
    ActionState,
    ActionStateStatus,
    ActionStatus,
    FunctionDefinition,
    NotificationLog,
    SideEffectOutbox,
)
from ontology.edits import AddObjectEdit, ObjectLocator, ModifyObjectEdit, TransactionEdit
from ontology.sql_repository import SqlActionRepository


def test_sql_repository_persists_records(tmp_path) -> None:
    db_url = f"sqlite:///{tmp_path}/test.db"
    repo = SqlActionRepository(db_url)

    execution = ActionExecution(
        execution_id="exec-1",
        action_name="Test",
        submitter="user",
        status=ActionStatus.queued,
        submitted_at=datetime.utcnow(),
        input_payload={"a": 1},
    )
    execution.ontology_edit = TransactionEdit(
        edits=[AddObjectEdit(object_type="Loan", primary_key="loan-1", properties={"status": "NEW"})]
    )
    execution.compensation_edit = TransactionEdit(
        edits=[
            ModifyObjectEdit(
                locator=ObjectLocator("Loan", "loan-1", version=1),
                properties={"status": "REVERTED"},
            )
        ]
    )
    repo.add_execution(execution)
    repo.add_log(
        ActionLog(
            execution_id="exec-1",
            event_type="submitted",
            payload={"a": 1},
            created_at=datetime.utcnow(),
        )
    )
    repo.add_revert(
        ActionRevert(
            revert_id="rev-1",
            original_execution_id="exec-1",
            revert_execution_id="rev-exec-1",
            status=ActionStatus.reverted,
            created_at=datetime.utcnow(),
            reason="test",
        )
    )
    repo.add_notification_log(
        NotificationLog(
            execution_id="exec-1",
            channel="email",
            subject="hello",
            payload={"body": "hi"},
            created_at=datetime.utcnow(),
        )
    )
    repo.add_outbox(
        SideEffectOutbox(
            outbox_id="out-1",
            execution_id="exec-1",
            effect_type="notify",
            payload={"msg": "ok"},
        )
    )
    repo.add_action_state(
        ActionState(
            action_id="state-1",
            execution_id="exec-1",
            status=ActionStateStatus.pending,
            intent_payload={"edits": {"type": "transaction", "edits": []}, "side_effects": []},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    repo.add_function(
        FunctionDefinition(
            name="Fn",
            runtime="python",
            code_ref="mod.fn",
            input_schema={"x": "int"},
            output_schema={"y": "int"},
            version=1,
        )
    )
    repo.add_action(
        ActionDefinition(
            name="Action",
            description="Test",
            function_name="Fn",
            input_schema={"x": "int"},
            output_schema={"y": "int"},
            version=1,
        )
    )

    pending = repo.claim_pending_outbox()
    assert pending[0].outbox_id == "out-1"
    assert repo.get_action("Action", version=1) is not None
    assert repo.get_function("Fn", version=1) is not None
