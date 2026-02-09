from ontology import DataFunnelService, InMemoryGraphStore
from ontology.edits import AddObjectEdit, ObjectLocator, TransactionEdit


def test_data_funnel_service_validator_runs() -> None:
    store = InMemoryGraphStore()
    called = {}

    def validator(edit: TransactionEdit) -> None:
        called["ok"] = True
        if edit.is_empty():
            raise ValueError("empty edit")

    service = DataFunnelService(store, validator=validator)
    result = service.apply(TransactionEdit())

    assert called["ok"] is True
    assert result.applied is False


def test_data_funnel_service_records_action_id() -> None:
    store = InMemoryGraphStore()
    service = DataFunnelService(store)
    edit = TransactionEdit(edits=[AddObjectEdit(object_type="Loan", primary_key="loan-9", properties={"status": "NEW"})])

    result = service.apply(edit, action_id="exec-9")

    assert result.applied is True
    obj = store.get_object(ObjectLocator("Loan", "loan-9"))
    assert obj.properties["last_modified_by_action_id"] == "exec-9"


def test_data_funnel_service_validation_chain() -> None:
    store = InMemoryGraphStore()
    called = {}

    def validator_one(edit: TransactionEdit) -> None:
        called["one"] = True

    def validator_two(edit: TransactionEdit) -> None:
        called["two"] = True

    service = DataFunnelService(store, validators=[validator_one, validator_two])
    result = service.apply(TransactionEdit())

    assert called == {"one": True, "two": True}
    assert result.applied is True
