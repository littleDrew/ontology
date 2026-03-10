import os
from datetime import datetime

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("pymysql")

from ontology import ActionDefinition, ActionExecution, ActionExecutionMode, ActionStatus, ActionTargetType, FunctionDefinition
from ontology.action.storage.sql_repository import SqlActionRepository


def test_sql_repository_mysql_smoke() -> None:
    db_url = os.getenv("MYSQL_TEST_URL")
    if not db_url:
        pytest.skip("MYSQL_TEST_URL not configured")

    repo = SqlActionRepository(db_url)
    suffix = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    function_name = f"FnMysql{suffix}"
    action_name = f"ActionMysql{suffix}"
    execution_id = f"exec-mysql-{suffix}"

    repo.add_function(
        FunctionDefinition(
            name=function_name,
            runtime="python",
            code_ref="inline://mysql-smoke",
            input_schema={"x": "int"},
            output_schema={"y": "int"},
            version=1,
        )
    )
    repo.add_action(
        ActionDefinition(
            name=action_name,
            description="mysql smoke",
            function_name=function_name,
            execution_mode=ActionExecutionMode.sandbox,
            target_type=ActionTargetType.entity,
            target_api_name="User",
            input_schema={"x": "int"},
            output_schema={"y": "int"},
            version=1,
        )
    )
    repo.add_execution(
        ActionExecution(
            execution_id=execution_id,
            action_name=action_name,
            submitter="mysql-user",
            status=ActionStatus.queued,
            submitted_at=datetime.utcnow(),
            input_payload={"x": 1},
        )
    )

    assert repo.get_function(function_name, version=1) is not None
    action = repo.get_action(action_name, version=1)
    assert action is not None
    assert action.execution_mode == ActionExecutionMode.sandbox
    assert action.target_type == ActionTargetType.entity
    assert action.target_api_name == "User"
    assert repo.get_execution(execution_id) is not None
