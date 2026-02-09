from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ontology.edits import (
    AddLinkEdit,
    AddObjectEdit,
    DeleteLinkEdit,
    DeleteObjectEdit,
    ModifyObjectEdit,
    ObjectInstance,
    ObjectLocator,
    OntologyEdit,
    TransactionEdit,
)


class EditRecorder:
    def __init__(self) -> None:
        self._edits: List[OntologyEdit] = []
        self._pending_modifications: Dict[ObjectLocator, Dict[str, Any]] = {}

    def add_object(self, object_type: str, primary_key: str) -> AddObjectEdit:
        edit = AddObjectEdit(object_type=object_type, primary_key=primary_key, properties={})
        self._edits.append(edit)
        return edit

    def delete_object(self, locator: ObjectLocator) -> None:
        self._edits.append(DeleteObjectEdit(locator))

    def modify_object(self, locator: ObjectLocator, properties: Dict[str, Any]) -> None:
        current = self._pending_modifications.setdefault(locator, {})
        current.update(properties)

    def add_link(self, link_type: str, from_locator: ObjectLocator, to_locator: ObjectLocator) -> None:
        self._edits.append(AddLinkEdit(link_type=link_type, from_locator=from_locator, to_locator=to_locator))

    def delete_link(self, link_type: str, from_locator: ObjectLocator, to_locator: ObjectLocator) -> None:
        self._edits.append(DeleteLinkEdit(link_type=link_type, from_locator=from_locator, to_locator=to_locator))

    def flush(self) -> TransactionEdit:
        for locator, properties in self._pending_modifications.items():
            self._edits.append(ModifyObjectEdit(locator=locator, properties=dict(properties)))
        self._pending_modifications.clear()
        return TransactionEdit(edits=list(self._edits))


@dataclass
class LinkCollection:
    link_type: str
    source: "EditableObject"
    recorder: EditRecorder

    def add(self, target: "EditableObject | ObjectInstance") -> None:
        self.recorder.add_link(self.link_type, self.source.locator(), _locator_from_target(target))

    def remove(self, target: "EditableObject | ObjectInstance") -> None:
        self.recorder.delete_link(self.link_type, self.source.locator(), _locator_from_target(target))


class EditableObject:
    def __init__(
        self,
        object_type: str,
        primary_key: str,
        recorder: EditRecorder,
        instance: Optional[ObjectInstance] = None,
        create_edit: Optional[AddObjectEdit] = None,
    ) -> None:
        object.__setattr__(self, "_object_type", object_type)
        object.__setattr__(self, "_primary_key", primary_key)
        object.__setattr__(self, "_recorder", recorder)
        object.__setattr__(self, "_instance", instance)
        object.__setattr__(self, "_create_edit", create_edit)
        object.__setattr__(self, "_dirty", {})

    def locator(self) -> ObjectLocator:
        version = self._instance.version if self._instance else None
        return ObjectLocator(self._object_type, self._primary_key, version=version)

    def __getattr__(self, item: str) -> Any:
        if item in self._dirty:
            return self._dirty[item]
        if self._instance and item in self._instance.properties:
            return self._instance.properties.get(item)
        return LinkCollection(item, self, self._recorder)

    def __setattr__(self, key: str, value: Any) -> None:
        if key.startswith("_"):
            object.__setattr__(self, key, value)
            return
        if self._create_edit is not None:
            self._create_edit.properties[key] = value
            self._dirty[key] = value
            return
        self._dirty[key] = value
        self._recorder.modify_object(self.locator(), {key: value})


class EditObjectType:
    def __init__(self, object_type: str, recorder: EditRecorder) -> None:
        self._object_type = object_type
        self._recorder = recorder

    def create(self, primary_key: str | int) -> EditableObject:
        key = str(primary_key)
        create_edit = self._recorder.add_object(self._object_type, key)
        return EditableObject(self._object_type, key, self._recorder, create_edit=create_edit)

    def edit(self, instance: ObjectInstance) -> EditableObject:
        return EditableObject(
            self._object_type,
            instance.primary_key,
            self._recorder,
            instance=instance,
        )

    def delete(self, instance: ObjectInstance | ObjectLocator) -> None:
        locator = instance if isinstance(instance, ObjectLocator) else instance.locator()
        self._recorder.delete_object(locator)


class EditObjectsAccessor:
    def __init__(self, recorder: EditRecorder) -> None:
        self._recorder = recorder

    def __getattr__(self, item: str) -> EditObjectType:
        return EditObjectType(item, self._recorder)


class EditSession:
    def __init__(self) -> None:
        self._recorder = EditRecorder()
        self.objects = EditObjectsAccessor(self._recorder)

    def get_edits(self) -> TransactionEdit:
        return self._recorder.flush()


def _locator_from_target(target: EditableObject | ObjectInstance) -> ObjectLocator:
    if isinstance(target, EditableObject):
        return target.locator()
    return target.locator()
