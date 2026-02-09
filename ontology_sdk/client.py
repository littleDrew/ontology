from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from ontology.edits import ObjectInstance, ObjectLocator
from ontology.storage import GraphStore

from .edits import EditSession


@dataclass
class ObjectTypeClient:
    object_type: str
    store: Optional[GraphStore]
    base_url: Optional[str]
    http_client: Optional[Any]

    def get(self, primary_key: str) -> ObjectInstance:
        locator = ObjectLocator(self.object_type, primary_key)
        if self.store is not None:
            return self.store.get_object(locator)
        if self.base_url and self.http_client:
            response = self.http_client.get(f"{self.base_url}/objects/{self.object_type}/{primary_key}")
            response.raise_for_status()
            data = response.json()
            return ObjectInstance(
                object_type=data["object_type"],
                primary_key=data["primary_key"],
                properties=data["properties"],
                version=data.get("version"),
            )
        raise ValueError("No store or HTTP client configured")

    def list(self, limit: int = 100, offset: int = 0) -> list[ObjectInstance]:
        if self.store is not None:
            return self.store.list_objects(self.object_type, limit=limit, offset=offset)
        if self.base_url and self.http_client:
            response = self.http_client.get(
                f"{self.base_url}/objects/{self.object_type}",
                params={"limit": limit, "offset": offset},
            )
            response.raise_for_status()
            data = response.json()
            return [
                ObjectInstance(
                    object_type=item["object_type"],
                    primary_key=item["primary_key"],
                    properties=item["properties"],
                    version=item.get("version"),
                )
                for item in data
            ]
        raise ValueError("No store or HTTP client configured")


class ObjectsClient:
    def __init__(
        self,
        store: Optional[GraphStore],
        base_url: Optional[str],
        http_client: Optional[Any],
    ) -> None:
        self._store = store
        self._base_url = base_url
        self._http_client = http_client

    def get(self, object_type: str, primary_key: str) -> ObjectInstance:
        locator = ObjectLocator(object_type, primary_key)
        if self._store is not None:
            return self._store.get_object(locator)
        if self._base_url and self._http_client:
            response = self._http_client.get(f"{self._base_url}/objects/{object_type}/{primary_key}")
            response.raise_for_status()
            data = response.json()
            return ObjectInstance(
                object_type=data["object_type"],
                primary_key=data["primary_key"],
                properties=data["properties"],
                version=data.get("version"),
            )
        raise ValueError("No store or HTTP client configured")

    def list(self, object_type: str, limit: int = 100, offset: int = 0) -> list[ObjectInstance]:
        if self._store is not None:
            return self._store.list_objects(object_type, limit=limit, offset=offset)
        if self._base_url and self._http_client:
            response = self._http_client.get(
                f"{self._base_url}/objects/{object_type}",
                params={"limit": limit, "offset": offset},
            )
            response.raise_for_status()
            data = response.json()
            return [
                ObjectInstance(
                    object_type=item["object_type"],
                    primary_key=item["primary_key"],
                    properties=item["properties"],
                    version=item.get("version"),
                )
                for item in data
            ]
        raise ValueError("No store or HTTP client configured")

    def __getattr__(self, item: str) -> ObjectTypeClient:
        return ObjectTypeClient(item, self._store, self._base_url, self._http_client)


class OntologyClient:
    def __init__(
        self,
        store: Optional[GraphStore],
        base_url: Optional[str],
        http_client: Optional[Any],
    ) -> None:
        self._store = store
        self._base_url = base_url
        self._http_client = http_client
        self.objects = ObjectsClient(store, base_url, http_client)

    def edits(self) -> EditSession:
        return EditSession()


class FoundryClient:
    def __init__(
        self,
        store: Optional[GraphStore] = None,
        base_url: Optional[str] = None,
        http_client: Optional[Any] = None,
    ) -> None:
        self.ontology = OntologyClient(store, base_url, http_client)
