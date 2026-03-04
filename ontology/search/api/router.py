from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ontology.action.api.schemas import ObjectResponse
from ontology.search.storage.service import SearchService


def create_router(search_service: SearchService) -> APIRouter:
    router = APIRouter()

    @router.get('/objects/{object_type}/{primary_key}', response_model=ObjectResponse)
    def get_object(object_type: str, primary_key: str) -> ObjectResponse:
        try:
            instance = search_service.get_object(object_type, primary_key)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return ObjectResponse(
            object_type=instance.object_type,
            primary_key=instance.primary_key,
            properties=instance.properties,
            version=instance.version,
        )

    @router.get('/objects/{object_type}', response_model=list[ObjectResponse])
    def list_objects(
        object_type: str,
        limit: int = Query(100, ge=1, le=1000),
        offset: int = Query(0, ge=0),
    ) -> list[ObjectResponse]:
        instances = search_service.list_objects(object_type, limit=limit, offset=offset)
        return [
            ObjectResponse(
                object_type=instance.object_type,
                primary_key=instance.primary_key,
                properties=instance.properties,
                version=instance.version,
            )
            for instance in instances
        ]

    return router
