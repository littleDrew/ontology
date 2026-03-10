from ontology_sdk import OntologyEdits
from ontology.action.storage.edits import AddObjectEdit, ModifyObjectEdit, ObjectLocator


def test_sdk_capture_and_normalize() -> None:
    edits = OntologyEdits()
    edits.add_object("Loan", "loan-1", {"status": "NEW"})
    edits.modify_object(ObjectLocator("Loan", "loan-1"), {"status": "APPROVED"})
    edits.modify_object(ObjectLocator("Loan", "loan-1"), {"amount": 200})

    tx = edits.get_transaction_edit()

    assert len(tx.edits) == 2
    assert isinstance(tx.edits[0], AddObjectEdit)
    assert isinstance(tx.edits[1], ModifyObjectEdit)
    assert tx.edits[1].properties == {"status": "APPROVED", "amount": 200}
