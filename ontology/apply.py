from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional, Sequence

from .edits import TransactionEdit
from .storage import GraphStore


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


class DataFunnelService:
    def __init__(
        self,
        store: GraphStore,
        validator: Optional[ValidationHook] = None,
        validators: Optional[Iterable[ValidationHook]] = None,
    ) -> None:
        self._store = store
        self._validator = validator
        self._validation_chain = ValidationChain(tuple(validators or ()))

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
