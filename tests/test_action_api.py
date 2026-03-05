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
    ObjectLocator,
)
from ontology.action.execution.runtime import function_action
from ontology.main import create_app


@function_action
def set_status(loan, context, status: str) -> str:
    loan.status = status
    return "ok"


def _build_app(include_legacy_routes: bool = True):
    store = InMemoryGraphStore()
    repo = InMemoryActionRepository()
    store.add_object("Loan", "loan-1", {"status": "PENDING"})
    runner = ActionRunner()
    runner.register("approve", set_status)
    service = ActionService(repo, runner, DataFunnelService(store))
    definition = ActionDefinition(
        name="Approve",
        description="Approve loan",
        function_name="approve",
        input_schema={"status": "string"},
        output_schema={"result": "string"},
        version=1,
    )
    repo.add_action(definition)
    app = create_app(store, action_service=service, repository=repo, include_legacy_routes=include_legacy_routes)
    return app, store


def test_action_apply_and_get_v1() -> None:
    app, store = _build_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/actions/Approve/apply",
        json={
            "version": 1,
            "submitter": "user-1",
            "input_payload": {"status": "APPROVED"},
            "input_instances": {"loan": {"object_type": "Loan", "primary_key": "loan-1"}},
        },
    )
    assert response.status_code == 200
    execution_id = response.json()["execution_id"]

    read_response = client.get(f"/api/v1/actions/executions/{execution_id}")
    assert read_response.status_code == 200
    assert read_response.json()["action_name"] == "Approve"
    assert read_response.json()["status"] == "succeeded"

    updated = store.get_object(ObjectLocator("Loan", "loan-1"))
    assert updated.properties["status"] == "APPROVED"


def test_legacy_routes_can_be_disabled() -> None:
    app, _ = _build_app(include_legacy_routes=False)
    client = TestClient(app)

    response = client.post(
        "/actions/submit",
        json={"action_name": "Approve", "version": 1, "submitter": "user-1", "input_payload": {"status": "APPROVED"}},
    )
    assert response.status_code == 404


def test_search_routes_under_v1() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-1", {"status": "PENDING"})
    repo = InMemoryActionRepository()
    runner = ActionRunner()
    runner.register("approve", set_status)
    service = ActionService(repo, runner, DataFunnelService(store))
    app = create_app(store, action_service=service, repository=repo)
    client = TestClient(app)

    response = client.get('/api/v1/objects/Loan/loan-1')
    assert response.status_code == 200
    assert response.json()['primary_key'] == 'loan-1'


def test_root_redirects_to_docs() -> None:
    app, _ = _build_app()
    client = TestClient(app)

    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/docs"
