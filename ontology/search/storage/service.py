from __future__ import annotations

from ontology.action.storage.edits import ObjectLocator
from ontology.instance.api.service import InstanceService


class SearchService:
    def __init__(self, instance_service: InstanceService) -> None:
        self._instance_service = instance_service

    def get_object(self, object_type: str, primary_key: str):
        return self._instance_service.get_object(ObjectLocator(object_type, primary_key))

    def list_objects(self, object_type: str, limit: int = 100, offset: int = 0):
        return self._instance_service.list_objects(object_type, limit=limit, offset=offset)
