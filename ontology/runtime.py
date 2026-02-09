from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

from .edits import (
    AddLinkEdit,
    AddObjectEdit,
    DeleteLinkEdit,
    ModifyObjectEdit,
    ObjectInstance,
    ObjectLocator,
    OntologyEdit,
    TransactionEdit,
)


class EditBuilder:
    def __init__(self) -> None:
        self._edits: List[OntologyEdit] = []
        self._pending_modifications: Dict[ObjectLocator, Dict[str, Any]] = {}

    def add_object(self, object_type: str, primary_key: str, properties: Dict[str, Any]) -> None:
        self._edits.append(AddObjectEdit(object_type, primary_key, properties))

    def modify_object(self, locator: ObjectLocator, properties: Dict[str, Any]) -> None:
        current = self._pending_modifications.setdefault(locator, {})
        current.update(properties)

    def add_link(self, link_type: str, from_locator: ObjectLocator, to_locator: ObjectLocator) -> None:
        self._edits.append(AddLinkEdit(link_type, from_locator, to_locator))

    def remove_link(self, link_type: str, from_locator: ObjectLocator, to_locator: ObjectLocator) -> None:
        self._edits.append(DeleteLinkEdit(link_type, from_locator, to_locator))

    def flush(self) -> TransactionEdit:
        for locator, properties in self._pending_modifications.items():
            self._edits.append(ModifyObjectEdit(locator=locator, properties=dict(properties)))
        self._pending_modifications.clear()
        return TransactionEdit(edits=list(self._edits))


class ObjectProxy:
    def __init__(self, instance: ObjectInstance, builder: EditBuilder) -> None:
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_builder", builder)
        object.__setattr__(self, "_dirty", {})

    @property
    def object_type(self) -> str:
        return self._instance.object_type

    @property
    def primary_key(self) -> str:
        return self._instance.primary_key

    @property
    def version(self) -> Optional[int]:
        return self._instance.version

    def link_to(self, link_type: str, target: "ObjectProxy") -> None:
        self._builder.add_link(link_type, self._instance.locator(), target._instance.locator())

    def __getattr__(self, item: str) -> Any:
        if item in self._dirty:
            return self._dirty[item]
        return self._instance.properties.get(item)

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
            return
        self._dirty[key] = value
        self._builder.modify_object(self._instance.locator(), {key: value})


@dataclass
class Context:
    edit_builder: EditBuilder = field(default_factory=EditBuilder)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_object(self, object_type: str, primary_key: str, properties: Dict[str, Any]) -> None:
        self.edit_builder.add_object(object_type, primary_key, properties)


class ActionRunner:
    def __init__(self) -> None:
        self._registry: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, fn: Callable[..., Any]) -> None:
        self._registry[name] = fn

    def execute(
        self,
        fn: Callable[..., Any],
        input_instances: Dict[str, ObjectInstance],
        params: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        params = params or {}
        context = Context(metadata=metadata or {})
        proxies = {
            name: ObjectProxy(instance=instance, builder=context.edit_builder)
            for name, instance in input_instances.items()
        }
        result = fn(**proxies, **params, context=context)
        transaction = context.edit_builder.flush()
        return {
            "result": result,
            "edits": transaction,
        }


def function_action(fn: Callable[..., Any]) -> Callable[..., Any]:
    fn._is_action_function = True  # type: ignore[attr-defined]
    return fn
