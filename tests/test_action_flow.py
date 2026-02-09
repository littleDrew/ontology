import os

import pytest

from ontology import (
    ActionRunner,
    AddObjectEdit,
    DataFunnelService,
    InMemoryGraphStore,
    ObjectInstance,
    ObjectLocator,
)
from ontology.runtime import function_action
from ontology.storage import Neo4jGraphStore


@function_action
def approve_loan(loan: ObjectInstance, borrower: ObjectInstance, context) -> str:
    if loan.status != "PENDING":
        return "skipped"
    loan.status = "APPROVED"
    loan.approved_amount = loan.amount * 0.9
    loan.link_to("BORROWER", borrower)
    context.add_object(
        "AuditEvent",
        "audit-1",
        {"action": "approve_loan", "loan_id": loan.primary_key},
    )
    return "approved"


def test_action_function_applies_edits_in_memory() -> None:
    store = InMemoryGraphStore()
    store.add_object("Loan", "loan-1", {"amount": 1000, "status": "PENDING"})
    store.add_object("Borrower", "user-1", {"name": "Ada"})

    runner = ActionRunner()
    loan_instance = store.get_object(ObjectLocator("Loan", "loan-1"))
    borrower_instance = store.get_object(ObjectLocator("Borrower", "user-1"))

    result = runner.execute(
        approve_loan,
        {"loan": loan_instance, "borrower": borrower_instance},
    )

    apply_engine = DataFunnelService(store)
    apply_result = apply_engine.apply(result["edits"])

    assert apply_result.applied is True
    updated = store.get_object(ObjectLocator("Loan", "loan-1"))
    assert updated.properties["status"] == "APPROVED"
    assert updated.properties["approved_amount"] == 900.0
    assert updated.version == 2
    audit = store.get_object(ObjectLocator("AuditEvent", "audit-1"))
    assert audit.properties["loan_id"] == "loan-1"
    assert ("BORROWER", ("Loan", "loan-1"), ("Borrower", "user-1")) in store.links


def test_action_function_applies_edits_to_neo4j() -> None:
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    if not uri or not user or not password:
        pytest.skip("Neo4j credentials not configured")
    pytest.importorskip("neo4j")

    store = Neo4jGraphStore(uri=uri, user=user, password=password)
    with store._driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")

    store.apply_edit(AddObjectEdit("Loan", "loan-neo", {"amount": 500, "status": "PENDING"}))
    store.apply_edit(AddObjectEdit("Borrower", "borrower-neo", {"name": "Neo"}))

    runner = ActionRunner()
    loan_instance = store.get_object(ObjectLocator("Loan", "loan-neo"))
    borrower_instance = store.get_object(ObjectLocator("Borrower", "borrower-neo"))
    result = runner.execute(
        approve_loan,
        {"loan": loan_instance, "borrower": borrower_instance},
    )
    DataFunnelService(store).apply(result["edits"])

    updated = store.get_object(ObjectLocator("Loan", "loan-neo"))
    assert updated.properties["status"] == "APPROVED"
