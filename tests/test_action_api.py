import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from ontology import (
    ActionDefinition,
    ActionRunner,
    ActionService,
    DataFunnelService,
    InMemoryActionRepository,
    InMemoryGraphStore,
)
from ontology.api import create_app


def test_action_submit_and_get() -> None:
    store = InMemoryGraphStore()
    repo = InMemoryActionRepository()
    service = ActionService(repo, ActionRunner(), DataFunnelService(store))
    definition = ActionDefinition(
        name="Approve",
        description="Approve loan",
        function_name="approve",
        input_schema={"status": "string"},
        output_schema={"result": "string"},
        version=1,
    )
    repo.add_action(definition)

    app = create_app(store, action_service=service, repository=repo)
    client = TestClient(app)

    response = client.post(
        "/actions/submit",
        json={"action_name": "Approve", "version": 1, "submitter": "user-1", "input_payload": {"status": "OK"}},
    )
    assert response.status_code == 200
    execution_id = response.json()["execution_id"]

    read_response = client.get(f"/actions/{execution_id}")
    assert read_response.status_code == 200
    assert read_response.json()["action_name"] == "Approve"
