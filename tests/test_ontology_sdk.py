from datetime import datetime, timedelta

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from ontology import DataFunnelService, InMemoryGraphStore, ObjectLocator
from ontology.api import create_app
from ontology_sdk import FoundryClient


def test_sdk_edits_create_and_link() -> None:
    store = InMemoryGraphStore()
    store.add_object("Employee", "emp-1", {"name": "Ada"})

    app = create_app(store)
    http_client = TestClient(app)
    client = FoundryClient(base_url=str(http_client.base_url), http_client=http_client)
    employee = client.ontology.objects.get("Employee", "emp-1")
    edits_session = client.ontology.edits()

    new_ticket = edits_session.objects.Ticket.create("ticket-1")
    new_ticket.due_date = datetime.now() + timedelta(days=7)

    editable_employee = edits_session.objects.Employee.edit(employee)
    editable_employee.assigned_tickets.add(new_ticket)

    edits = edits_session.get_edits()
    DataFunnelService(store).apply(edits)

    ticket = store.get_object(ObjectLocator("Ticket", "ticket-1"))
    assert ticket.properties["due_date"] is not None
    assert ("assigned_tickets", ("Employee", "emp-1"), ("Ticket", "ticket-1")) in store.links
