from ontology import DataFunnelService, InMemoryGraphStore, InstanceService
from ontology.action.storage.edits import AddObjectEdit, ObjectLocator, TransactionEdit


def test_instance_service_apply_and_read() -> None:
    store = InMemoryGraphStore()
    service = InstanceService(store)

    tx = TransactionEdit(edits=[AddObjectEdit(object_type='Loan', primary_key='loan-i-1', properties={'status': 'NEW'})])
    result = service.apply(tx, action_id='exec-i-1')

    assert result.applied is True
    obj = service.get_object(ObjectLocator('Loan', 'loan-i-1'))
    assert obj.properties['status'] == 'NEW'
    assert obj.properties['last_modified_by_action_id'] == 'exec-i-1'


def test_instance_service_has_action_applied() -> None:
    store = InMemoryGraphStore()
    service = InstanceService(store)

    tx = TransactionEdit(edits=[AddObjectEdit(object_type='Loan', primary_key='loan-i-2', properties={'status': 'NEW'})])
    service.apply(tx, action_id='exec-i-2')

    assert service.has_action_applied('exec-i-2', edit_payload={'type': 'transaction', 'edits': [{'type': 'add_object', 'object_type': 'Loan', 'primary_key': 'loan-i-2', 'properties': {'status': 'NEW'}}]}) is True


def test_data_funnel_service_read_helpers() -> None:
    store = InMemoryGraphStore()
    funnel = DataFunnelService(store)

    tx = TransactionEdit(edits=[AddObjectEdit(object_type='Loan', primary_key='loan-f-1', properties={'status': 'NEW'})])
    funnel.apply(tx, action_id='exec-f-1')

    obj = funnel.get_object(ObjectLocator('Loan', 'loan-f-1'))
    assert obj is not None
    assert obj.properties['status'] == 'NEW'
    assert funnel.has_action_applied('exec-f-1', edit_payload={'type': 'transaction', 'edits': [{'type': 'add_object', 'object_type': 'Loan', 'primary_key': 'loan-f-1', 'properties': {'status': 'NEW'}}]}) is True
