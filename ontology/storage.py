from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Dict, Set, Tuple

from .edits import (
    AddLinkEdit,
    AddObjectEdit,
    DeleteLinkEdit,
    DeleteObjectEdit,
    edit_from_dict,
    ModifyObjectEdit,
    ObjectInstance,
    ObjectLocator,
    OntologyEdit,
    RemoveLinkEdit,
    TransactionEdit,
)


class GraphStore:
    def apply_edit(self, edit: OntologyEdit, action_id: str | None = None) -> None:
        raise NotImplementedError

    def get_object(self, locator: ObjectLocator) -> ObjectInstance:
        raise NotImplementedError

    def list_objects(self, object_type: str, limit: int = 100, offset: int = 0) -> list[ObjectInstance]:
        raise NotImplementedError

    def has_action_applied(self, action_id: str, edit_payload: Dict[str, Any] | None) -> bool:
        raise NotImplementedError


@dataclass
class InMemoryGraphStore(GraphStore):
    objects: Dict[Tuple[str, str], ObjectInstance]
    links: Set[Tuple[str, Tuple[str, str], Tuple[str, str]]]

    def __init__(self) -> None:
        self.objects = {}
        self.links = set()

    def add_object(
        self,
        object_type: str,
        primary_key: str,
        properties: Dict[str, Any],
        action_id: str | None = None,
    ) -> None:
        key = (object_type, primary_key)
        if key in self.objects:
            raise ValueError("Object already exists")
        stored_properties = dict(properties)
        if action_id:
            stored_properties["last_modified_by_action_id"] = action_id
        self.objects[key] = ObjectInstance(
            object_type=object_type,
            primary_key=primary_key,
            properties=stored_properties,
            version=1,
        )

    def modify_object(
        self,
        locator: ObjectLocator,
        properties: Dict[str, Any],
        action_id: str | None = None,
    ) -> None:
        key = (locator.object_type, locator.primary_key)
        instance = self.objects.get(key)
        if instance is None:
            raise ValueError("Object not found")
        if locator.version is not None and instance.version != locator.version:
            raise ValueError("Version conflict")
        instance.properties.update(properties)
        if action_id:
            instance.properties["last_modified_by_action_id"] = action_id
        instance.version = (instance.version or 0) + 1

    def add_link(self, link_type: str, from_locator: ObjectLocator, to_locator: ObjectLocator) -> None:
        self.links.add(
            (link_type, (from_locator.object_type, from_locator.primary_key), (to_locator.object_type, to_locator.primary_key))
        )

    def remove_link(self, link_type: str, from_locator: ObjectLocator, to_locator: ObjectLocator) -> None:
        self.links.discard(
            (link_type, (from_locator.object_type, from_locator.primary_key), (to_locator.object_type, to_locator.primary_key))
        )

    def apply_edit(self, edit: OntologyEdit, action_id: str | None = None) -> None:
        if isinstance(edit, TransactionEdit):
            for nested in edit.edits:
                self.apply_edit(nested, action_id=action_id)
            return
        if isinstance(edit, AddObjectEdit):
            self.add_object(edit.object_type, edit.primary_key, edit.properties, action_id=action_id)
            return
        if isinstance(edit, DeleteObjectEdit):
            self.delete_object(edit.locator)
            return
        if isinstance(edit, ModifyObjectEdit):
            self.modify_object(edit.locator, edit.properties, action_id=action_id)
            return
        if isinstance(edit, AddLinkEdit):
            self.add_link(edit.link_type, edit.from_locator, edit.to_locator)
            return
        if isinstance(edit, (RemoveLinkEdit, DeleteLinkEdit)):
            self.remove_link(edit.link_type, edit.from_locator, edit.to_locator)
            return
        raise ValueError(f"Unsupported edit: {edit}")

    def get_object(self, locator: ObjectLocator) -> ObjectInstance:
        key = (locator.object_type, locator.primary_key)
        instance = self.objects.get(key)
        if instance is None:
            raise ValueError("Object not found")
        return ObjectInstance(
            object_type=instance.object_type,
            primary_key=instance.primary_key,
            properties=dict(instance.properties),
            version=instance.version,
        )

    def list_objects(self, object_type: str, limit: int = 100, offset: int = 0) -> list[ObjectInstance]:
        results = [
            ObjectInstance(
                object_type=instance.object_type,
                primary_key=instance.primary_key,
                properties=dict(instance.properties),
                version=instance.version,
            )
            for (obj_type, _), instance in self.objects.items()
            if obj_type == object_type
        ]
        results.sort(key=lambda item: item.primary_key)
        return results[offset : offset + limit]

    def delete_object(self, locator: ObjectLocator) -> None:
        key = (locator.object_type, locator.primary_key)
        if key not in self.objects:
            raise ValueError("Object not found")
        del self.objects[key]
        self.links = {
            link
            for link in self.links
            if link[1] != key and link[2] != key
        }

    def has_action_applied(self, action_id: str, edit_payload: Dict[str, Any] | None) -> bool:
        if not edit_payload:
            return False
        edit = edit_from_dict(edit_payload)
        locators = _extract_locators(edit)
        if not locators:
            return False
        for locator in locators:
            key = (locator.object_type, locator.primary_key)
            instance = self.objects.get(key)
            if instance is None:
                return False
            if instance.properties.get("last_modified_by_action_id") != action_id:
                return False
        return True


class Neo4jGraphStore(GraphStore):
    def __init__(self, uri: str, user: str, password: str) -> None:
        neo4j_module = importlib.import_module("neo4j")
        self._driver = neo4j_module.GraphDatabase.driver(uri, auth=(user, password))

    def apply_edit(self, edit: OntologyEdit, action_id: str | None = None) -> None:
        if isinstance(edit, TransactionEdit):
            with self._driver.session() as session:
                session.execute_write(self._apply_transaction, edit, action_id)
            return
        with self._driver.session() as session:
            session.execute_write(self._apply_single, edit, action_id)

    def get_object(self, locator: ObjectLocator) -> ObjectInstance:
        label = self._escape_label(locator.object_type)
        query = f"MATCH (n:{label} {{primary_key: $primary_key}}) RETURN n"
        with self._driver.session() as session:
            record = session.run(query, primary_key=locator.primary_key).single()
        if record is None:
            raise ValueError("Object not found")
        node = record["n"]
        properties = dict(node)
        properties.pop("version", None)
        properties.pop("primary_key", None)
        return ObjectInstance(
            object_type=locator.object_type,
            primary_key=locator.primary_key,
            properties=properties,
            version=node.get("version"),
        )

    def list_objects(self, object_type: str, limit: int = 100, offset: int = 0) -> list[ObjectInstance]:
        label = self._escape_label(object_type)
        query = f"MATCH (n:{label}) RETURN n ORDER BY n.primary_key SKIP $offset LIMIT $limit"
        with self._driver.session() as session:
            records = session.run(query, offset=offset, limit=limit)
            results = []
            for record in records:
                node = record["n"]
                properties = dict(node)
                properties.pop("version", None)
                properties.pop("primary_key", None)
                results.append(
                    ObjectInstance(
                        object_type=object_type,
                        primary_key=node.get("primary_key"),
                        properties=properties,
                        version=node.get("version"),
                    )
                )
        return results

    def _apply_transaction(self, tx: Any, transaction: TransactionEdit, action_id: str | None) -> None:
        for edit in transaction.edits:
            self._apply_single(tx, edit, action_id)

    def _apply_single(self, tx: Any, edit: OntologyEdit, action_id: str | None) -> None:
        if isinstance(edit, AddObjectEdit):
            self._add_object(tx, edit, action_id)
            return
        if isinstance(edit, DeleteObjectEdit):
            self._delete_object(tx, edit)
            return
        if isinstance(edit, ModifyObjectEdit):
            self._modify_object(tx, edit, action_id)
            return
        if isinstance(edit, AddLinkEdit):
            self._add_link(tx, edit)
            return
        if isinstance(edit, (RemoveLinkEdit, DeleteLinkEdit)):
            self._remove_link(tx, edit)
            return
        raise ValueError(f"Unsupported edit: {edit}")

    def _add_object(self, tx: Any, edit: AddObjectEdit, action_id: str | None) -> None:
        label = self._escape_label(edit.object_type)
        exists_query = f"MATCH (n:{label} {{primary_key: $primary_key}}) RETURN n"
        if tx.run(exists_query, primary_key=edit.primary_key).single():
            raise ValueError("Object already exists")
        properties = dict(edit.properties)
        properties["primary_key"] = edit.primary_key
        properties["version"] = 1
        if action_id:
            properties["last_modified_by_action_id"] = action_id
        create_query = f"CREATE (n:{label}) SET n = $props"
        tx.run(create_query, props=properties)

    def _modify_object(self, tx: Any, edit: ModifyObjectEdit, action_id: str | None) -> None:
        label = self._escape_label(edit.locator.object_type)
        version_clause = ""
        params = {
            "primary_key": edit.locator.primary_key,
            "props": dict(edit.properties),
        }
        if action_id:
            params["props"]["last_modified_by_action_id"] = action_id
        if edit.locator.version is not None:
            version_clause = " AND n.version = $version"
            params["version"] = edit.locator.version
        query = (
            f"MATCH (n:{label} {{primary_key: $primary_key}})"
            f" WHERE true{version_clause}"
            " SET n += $props, n.version = coalesce(n.version, 0) + 1"
            " RETURN n"
        )
        record = tx.run(query, **params).single()
        if record is None:
            raise ValueError("Object not found or version conflict")

    def _delete_object(self, tx: Any, edit: DeleteObjectEdit) -> None:
        label = self._escape_label(edit.locator.object_type)
        query = f"MATCH (n:{label} {{primary_key: $primary_key}}) DETACH DELETE n RETURN count(n) as deleted"
        record = tx.run(query, primary_key=edit.locator.primary_key).single()
        if record is None or record["deleted"] == 0:
            raise ValueError("Object not found")

    def has_action_applied(self, action_id: str, edit_payload: Dict[str, Any] | None) -> bool:
        if not edit_payload:
            return False
        edit = edit_from_dict(edit_payload)
        locators = _extract_locators(edit)
        if not locators:
            return False
        with self._driver.session() as session:
            for locator in locators:
                label = self._escape_label(locator.object_type)
                query = (
                    f"MATCH (n:{label} {{primary_key: $primary_key}})"
                    " WHERE n.last_modified_by_action_id = $action_id"
                    " RETURN n LIMIT 1"
                )
                record = session.run(query, primary_key=locator.primary_key, action_id=action_id).single()
                if record is None:
                    return False
        return True

    def _add_link(self, tx: Any, edit: AddLinkEdit) -> None:
        from_label = self._escape_label(edit.from_locator.object_type)
        to_label = self._escape_label(edit.to_locator.object_type)
        rel_type = self._escape_label(edit.link_type)
        query = (
            f"MATCH (a:{from_label} {{primary_key: $from_pk}})"
            f" MATCH (b:{to_label} {{primary_key: $to_pk}})"
            f" MERGE (a)-[r:{rel_type}]->(b)"
            " RETURN r"
        )
        record = tx.run(
            query,
            from_pk=edit.from_locator.primary_key,
            to_pk=edit.to_locator.primary_key,
        ).single()
        if record is None:
            raise ValueError("Link endpoints not found")

    def _remove_link(self, tx: Any, edit: RemoveLinkEdit) -> None:
        from_label = self._escape_label(edit.from_locator.object_type)
        to_label = self._escape_label(edit.to_locator.object_type)
        rel_type = self._escape_label(edit.link_type)
        query = (
            f"MATCH (a:{from_label} {{primary_key: $from_pk}})"
            f"-[r:{rel_type}]->"
            f"(b:{to_label} {{primary_key: $to_pk}})"
            " DELETE r"
        )
        tx.run(
            query,
            from_pk=edit.from_locator.primary_key,
            to_pk=edit.to_locator.primary_key,
        )

    @staticmethod
    def _escape_label(label: str) -> str:
        return label.replace("`", "``")


def _extract_locators(edit: OntologyEdit) -> list[ObjectLocator]:
    if isinstance(edit, TransactionEdit):
        locators: list[ObjectLocator] = []
        for nested in edit.edits:
            locators.extend(_extract_locators(nested))
        return locators
    if isinstance(edit, AddObjectEdit):
        return [ObjectLocator(edit.object_type, edit.primary_key)]
    if isinstance(edit, ModifyObjectEdit):
        return [ObjectLocator(edit.locator.object_type, edit.locator.primary_key)]
    if isinstance(edit, DeleteObjectEdit):
        return [ObjectLocator(edit.locator.object_type, edit.locator.primary_key)]
    if isinstance(edit, (AddLinkEdit, RemoveLinkEdit, DeleteLinkEdit)):
        return [
            ObjectLocator(edit.from_locator.object_type, edit.from_locator.primary_key),
            ObjectLocator(edit.to_locator.object_type, edit.to_locator.primary_key),
        ]
    return []
