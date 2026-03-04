from __future__ import annotations

"""Phase-1 instance-side validation and apply service.

This module is the write boundary: it validates TransactionEdit payloads and
commits them through GraphStore in a single apply call.
"""

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from ontology.action.storage.edits import (
    AddLinkEdit,
    AddObjectEdit,
    DeleteLinkEdit,
    DeleteObjectEdit,
    ModifyObjectEdit,
    ObjectLocator,
    OntologyEdit,
    RemoveLinkEdit,
    TransactionEdit,
)
from ontology.instance.storage.graph_store import GraphStore


@dataclass
class DataFunnelResult:
    applied: bool
    error: str | None = None


ValidationHook = Callable[[TransactionEdit], None]


@dataclass
class ValidationChain:
    validators: Sequence[ValidationHook] = field(default_factory=tuple)

    def run(self, transaction: TransactionEdit) -> None:
        if not self.validators:
            raise ValueError("No validators configured")
        for validator in self.validators:
            validator(transaction)


def _validate_edit_shape(edit: OntologyEdit) -> None:
    if isinstance(edit, AddObjectEdit):
        if not edit.object_type or not edit.primary_key:
            raise ValueError("Invalid add object edit")
        return
    if isinstance(edit, ModifyObjectEdit):
        if not edit.locator.object_type or not edit.locator.primary_key:
            raise ValueError("Invalid modify object locator")
        if not edit.properties:
            raise ValueError("Modify edit must include at least one property")
        return
    if isinstance(edit, DeleteObjectEdit):
        if not edit.locator.object_type or not edit.locator.primary_key:
            raise ValueError("Invalid delete object locator")
        return
    if isinstance(edit, (AddLinkEdit, RemoveLinkEdit, DeleteLinkEdit)):
        if not edit.link_type:
            raise ValueError("Invalid link type")
        if not edit.from_locator.primary_key or not edit.to_locator.primary_key:
            raise ValueError("Invalid link locator")
        return


def validate_transaction_strong(transaction: TransactionEdit) -> None:
    """Validate basic shape and duplicate edit conflicts inside one transaction."""

    seen_add_objects: set[tuple[str, str]] = set()
    seen_delete_objects: set[tuple[str, str]] = set()

    for edit in transaction.edits:
        _validate_edit_shape(edit)
        if isinstance(edit, AddObjectEdit):
            key = (edit.object_type, edit.primary_key)
            if key in seen_add_objects:
                raise ValueError("Duplicate addObject in transaction")
            seen_add_objects.add(key)
        elif isinstance(edit, DeleteObjectEdit):
            key = (edit.locator.object_type, edit.locator.primary_key)
            if key in seen_delete_objects:
                raise ValueError("Duplicate deleteObject in transaction")
            seen_delete_objects.add(key)


class DataFunnelService:
    """Core write-path service used by ActionService apply phase."""

    def __init__(
        self,
        store: GraphStore,
        validator: Optional[ValidationHook] = None,
        validators: Optional[Iterable[ValidationHook]] = None,
    ) -> None:
        self._store = store
        self._validator = validator
        custom_validators = tuple(validators or ())
        self._validation_chain = ValidationChain((validate_transaction_strong, *custom_validators))

    @property
    def store(self) -> GraphStore:
        return self._store

    def apply(self, transaction: TransactionEdit, action_id: str | None = None) -> DataFunnelResult:
        try:
            if self._validator:
                self._validator(transaction)
            if self._validation_chain.validators:
                self._validation_chain.run(transaction)
            self._store.apply_edit(transaction, action_id=action_id)
        except Exception as exc:  # noqa: BLE001
            return DataFunnelResult(applied=False, error=str(exc))
        return DataFunnelResult(applied=True)


    def get_object(self, locator: ObjectLocator):
        """Read helper used by ActionService during input instance resolution."""
        return self.store.get_object(locator)

    def list_objects(self, object_type: str, limit: int = 100, offset: int = 0):
        """Read helper used by search/read paths in lightweight deployments."""
        return self.store.list_objects(object_type=object_type, limit=limit, offset=offset)

    def has_action_applied(self, action_id: str, edit_payload: dict | None = None) -> bool:
        """Expose idempotency/reconciliation lookup from underlying store."""
        return self.store.has_action_applied(action_id, edit_payload)

class InstanceService:
    """Unified phase-1 instance service for write/apply and basic reads."""

    def __init__(
        self,
        store: GraphStore,
        validator: Optional[ValidationHook] = None,
        validators: Optional[Iterable[ValidationHook]] = None,
    ) -> None:
        self._funnel = DataFunnelService(store=store, validator=validator, validators=validators)

    @property
    def store(self) -> GraphStore:
        return self._funnel.store

    def apply(self, transaction: TransactionEdit, action_id: str | None = None) -> DataFunnelResult:
        return self._funnel.apply(transaction=transaction, action_id=action_id)

    def get_object(self, locator: ObjectLocator):
        return self._funnel.get_object(locator)

    def list_objects(self, object_type: str, limit: int = 100, offset: int = 0):
        return self._funnel.list_objects(object_type=object_type, limit=limit, offset=offset)

    def has_action_applied(self, action_id: str, edit_payload: dict | None = None) -> bool:
        return self._funnel.has_action_applied(action_id, edit_payload)
