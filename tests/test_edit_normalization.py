from ontology.action.storage.edits import (
    AddLinkEdit,
    AddObjectEdit,
    DeleteObjectEdit,
    ModifyObjectEdit,
    ObjectLocator,
    RemoveLinkEdit,
    TransactionEdit,
    normalize_transaction_edit,
)


def test_normalize_create_then_delete_cancelled() -> None:
    tx = TransactionEdit(
        edits=[
            AddObjectEdit("Loan", "loan-1", {"status": "NEW"}),
            DeleteObjectEdit(ObjectLocator("Loan", "loan-1")),
        ]
    )
    normalized = normalize_transaction_edit(tx)
    assert normalized.edits == []


def test_normalize_modify_merged() -> None:
    tx = TransactionEdit(
        edits=[
            ModifyObjectEdit(ObjectLocator("Loan", "loan-1", version=1), {"status": "PENDING"}),
            ModifyObjectEdit(ObjectLocator("Loan", "loan-1", version=1), {"amount": 100}),
        ]
    )
    normalized = normalize_transaction_edit(tx)
    assert len(normalized.edits) == 1
    edit = normalized.edits[0]
    assert isinstance(edit, ModifyObjectEdit)
    assert edit.properties == {"status": "PENDING", "amount": 100}


def test_normalize_link_add_remove_cancelled() -> None:
    from_locator = ObjectLocator("Loan", "loan-1")
    to_locator = ObjectLocator("Borrower", "b-1")
    tx = TransactionEdit(
        edits=[
            AddLinkEdit("BORROWER", from_locator, to_locator),
            RemoveLinkEdit("BORROWER", from_locator, to_locator),
        ]
    )
    normalized = normalize_transaction_edit(tx)
    assert normalized.edits == []
