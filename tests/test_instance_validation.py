from ontology import DataFunnelService, InMemoryGraphStore, ObjectLocator
from ontology.action.storage.edits import AddObjectEdit, DeleteObjectEdit, ModifyObjectEdit, TransactionEdit


def test_instance_validation_rejects_empty_modify_properties() -> None:
    store = InMemoryGraphStore()
    service = DataFunnelService(store)
    tx = TransactionEdit(
        edits=[ModifyObjectEdit(locator=ObjectLocator('Loan', 'loan-1', version=1), properties={})]
    )

    result = service.apply(tx)

    assert result.applied is False
    assert 'at least one property' in (result.error or '')


def test_instance_validation_rolls_back_on_conflict() -> None:
    store = InMemoryGraphStore()
    service = DataFunnelService(store)

    service.apply(TransactionEdit(edits=[AddObjectEdit('Loan', 'loan-1', {'status': 'NEW'})]))

    tx = TransactionEdit(
        edits=[
            AddObjectEdit('Loan', 'loan-2', {'status': 'NEW'}),
            AddObjectEdit('Loan', 'loan-1', {'status': 'DUP'}),
        ]
    )
    result = service.apply(tx)

    assert result.applied is False
    # rollback should remove loan-2 created before failure in the same transaction
    objects = store.list_objects('Loan')
    assert [obj.primary_key for obj in objects] == ['loan-1']


def test_instance_validation_occ_delete_version_conflict() -> None:
    store = InMemoryGraphStore()
    service = DataFunnelService(store)
    service.apply(TransactionEdit(edits=[AddObjectEdit('Loan', 'loan-3', {'status': 'NEW'})]))

    tx = TransactionEdit(edits=[DeleteObjectEdit(locator=ObjectLocator('Loan', 'loan-3', version=2))])
    result = service.apply(tx)

    assert result.applied is False
    assert 'Version conflict' in (result.error or '')
