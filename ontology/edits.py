from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ObjectLocator:
    object_type: str
    primary_key: str
    version: Optional[int] = None


@dataclass
class ObjectInstance:
    object_type: str
    primary_key: str
    properties: Dict[str, Any]
    version: Optional[int] = None

    def locator(self) -> ObjectLocator:
        return ObjectLocator(
            object_type=self.object_type,
            primary_key=self.primary_key,
            version=self.version,
        )


@dataclass
class OntologyEdit:
    """Base class for edits."""


@dataclass
class AddObjectEdit(OntologyEdit):
    object_type: str
    primary_key: str
    properties: Dict[str, Any]


@dataclass
class DeleteObjectEdit(OntologyEdit):
    locator: ObjectLocator


@dataclass
class ModifyObjectEdit(OntologyEdit):
    locator: ObjectLocator
    properties: Dict[str, Any]


@dataclass
class AddLinkEdit(OntologyEdit):
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class RemoveLinkEdit(OntologyEdit):
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class DeleteLinkEdit(OntologyEdit):
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class TransactionEdit(OntologyEdit):
    edits: List[OntologyEdit] = field(default_factory=list)
    assertions: Sequence[str] = field(default_factory=list)

    def extend(self, items: Iterable[OntologyEdit]) -> None:
        self.edits.extend(items)

    def is_empty(self) -> bool:
        return not self.edits


def locator_to_dict(locator: ObjectLocator) -> Dict[str, Any]:
    return {
        "object_type": locator.object_type,
        "primary_key": locator.primary_key,
        "version": locator.version,
    }


def locator_from_dict(data: Dict[str, Any]) -> ObjectLocator:
    return ObjectLocator(
        object_type=data["object_type"],
        primary_key=data["primary_key"],
        version=data.get("version"),
    )


def edit_to_dict(edit: OntologyEdit) -> Dict[str, Any]:
    if isinstance(edit, TransactionEdit):
        return {
            "type": "transaction",
            "edits": [edit_to_dict(item) for item in edit.edits],
            "assertions": list(edit.assertions),
        }
    if isinstance(edit, AddObjectEdit):
        return {
            "type": "add_object",
            "object_type": edit.object_type,
            "primary_key": edit.primary_key,
            "properties": edit.properties,
        }
    if isinstance(edit, DeleteObjectEdit):
        return {"type": "delete_object", "locator": locator_to_dict(edit.locator)}
    if isinstance(edit, ModifyObjectEdit):
        return {
            "type": "modify_object",
            "locator": locator_to_dict(edit.locator),
            "properties": edit.properties,
        }
    if isinstance(edit, AddLinkEdit):
        return {
            "type": "add_link",
            "link_type": edit.link_type,
            "from_locator": locator_to_dict(edit.from_locator),
            "to_locator": locator_to_dict(edit.to_locator),
        }
    if isinstance(edit, RemoveLinkEdit):
        return {
            "type": "remove_link",
            "link_type": edit.link_type,
            "from_locator": locator_to_dict(edit.from_locator),
            "to_locator": locator_to_dict(edit.to_locator),
        }
    if isinstance(edit, DeleteLinkEdit):
        return {
            "type": "delete_link",
            "link_type": edit.link_type,
            "from_locator": locator_to_dict(edit.from_locator),
            "to_locator": locator_to_dict(edit.to_locator),
        }
    raise ValueError(f"Unsupported edit type: {type(edit)}")


def edit_from_dict(data: Dict[str, Any]) -> OntologyEdit:
    edit_type = data["type"]
    if edit_type == "transaction":
        return TransactionEdit(
            edits=[edit_from_dict(item) for item in data.get("edits", [])],
            assertions=list(data.get("assertions", [])),
        )
    if edit_type == "add_object":
        return AddObjectEdit(
            object_type=data["object_type"],
            primary_key=data["primary_key"],
            properties=data["properties"],
        )
    if edit_type == "delete_object":
        return DeleteObjectEdit(locator=locator_from_dict(data["locator"]))
    if edit_type == "modify_object":
        return ModifyObjectEdit(
            locator=locator_from_dict(data["locator"]),
            properties=data["properties"],
        )
    if edit_type == "add_link":
        return AddLinkEdit(
            link_type=data["link_type"],
            from_locator=locator_from_dict(data["from_locator"]),
            to_locator=locator_from_dict(data["to_locator"]),
        )
    if edit_type == "remove_link":
        return RemoveLinkEdit(
            link_type=data["link_type"],
            from_locator=locator_from_dict(data["from_locator"]),
            to_locator=locator_from_dict(data["to_locator"]),
        )
    if edit_type == "delete_link":
        return DeleteLinkEdit(
            link_type=data["link_type"],
            from_locator=locator_from_dict(data["from_locator"]),
            to_locator=locator_from_dict(data["to_locator"]),
        )
    raise ValueError(f"Unsupported edit type: {edit_type}")
