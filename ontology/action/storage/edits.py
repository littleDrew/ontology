from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class ObjectLocator:
    """Stable locator for one ontology object (type + key + optional version)."""
    object_type: str
    primary_key: str
    version: Optional[int] = None


@dataclass
class ObjectInstance:
    """In-memory object instance snapshot."""
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
class RelationInstance:
    """In-memory relation instance snapshot by link type and endpoints."""
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class OntologyEdit:
    """Base class for edits."""


@dataclass
class AddObjectEdit(OntologyEdit):
    """Create a new object."""
    object_type: str
    primary_key: str
    properties: Dict[str, Any]


@dataclass
class DeleteObjectEdit(OntologyEdit):
    """Delete an existing object."""
    locator: ObjectLocator


@dataclass
class ModifyObjectEdit(OntologyEdit):
    """Modify properties of an existing object."""
    locator: ObjectLocator
    properties: Dict[str, Any]


@dataclass
class AddLinkEdit(OntologyEdit):
    """Create a relation between two objects."""
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class RemoveLinkEdit(OntologyEdit):
    """Remove a relation between two objects."""
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class DeleteLinkEdit(OntologyEdit):
    """Compatibility alias for link removal in legacy payloads."""
    link_type: str
    from_locator: ObjectLocator
    to_locator: ObjectLocator


@dataclass
class TransactionEdit(OntologyEdit):
    """Container for a set of ontology edits applied atomically."""
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



def _locator_key(locator: ObjectLocator) -> tuple[str, str]:
    return (locator.object_type, locator.primary_key)


def normalize_transaction_edit(transaction: TransactionEdit) -> TransactionEdit:
    """Normalize captured edits for deterministic apply semantics.

    Rules:
    - create then delete same object => both removed
    - multiple modify same object => merged with last-write-wins per property
    - duplicate links deduped; add/remove same link in same tx cancels out
    """

    add_objects: dict[tuple[str, str], AddObjectEdit] = {}
    modify_objects: dict[tuple[str, str], ModifyObjectEdit] = {}
    delete_objects: dict[tuple[str, str], DeleteObjectEdit] = {}
    add_links: dict[tuple[str, tuple[str, str], tuple[str, str]], AddLinkEdit] = {}
    remove_links: dict[tuple[str, tuple[str, str], tuple[str, str]], RemoveLinkEdit] = {}

    for edit in transaction.edits:
        if isinstance(edit, AddObjectEdit):
            key = (edit.object_type, edit.primary_key)
            add_objects[key] = edit
            continue

        if isinstance(edit, ModifyObjectEdit):
            key = _locator_key(edit.locator)
            if key in delete_objects:
                continue
            existing = modify_objects.get(key)
            if existing is None:
                modify_objects[key] = ModifyObjectEdit(locator=edit.locator, properties=dict(edit.properties))
            else:
                merged = dict(existing.properties)
                merged.update(edit.properties)
                locator = edit.locator if edit.locator.version is not None else existing.locator
                modify_objects[key] = ModifyObjectEdit(locator=locator, properties=merged)
            continue

        if isinstance(edit, DeleteObjectEdit):
            key = _locator_key(edit.locator)
            if key in add_objects:
                add_objects.pop(key, None)
                modify_objects.pop(key, None)
                continue
            modify_objects.pop(key, None)
            delete_objects[key] = edit
            continue

        if isinstance(edit, AddLinkEdit):
            key = (edit.link_type, _locator_key(edit.from_locator), _locator_key(edit.to_locator))
            if key in remove_links:
                remove_links.pop(key, None)
                continue
            add_links[key] = edit
            continue

        if isinstance(edit, RemoveLinkEdit):
            key = (edit.link_type, _locator_key(edit.from_locator), _locator_key(edit.to_locator))
            if key in add_links:
                add_links.pop(key, None)
                continue
            remove_links[key] = edit
            continue

    normalized: list[OntologyEdit] = []
    normalized.extend(add_objects.values())
    normalized.extend(modify_objects.values())
    normalized.extend(delete_objects.values())
    normalized.extend(add_links.values())
    normalized.extend(remove_links.values())
    return TransactionEdit(edits=normalized, assertions=transaction.assertions)
