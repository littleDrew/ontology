"""Top-level application entrypoints for ontology."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .action.api.service import ActionService
from .instance.storage.graph_store import GraphStore
from .instance.api.service import InstanceService
from .action.storage.repository import ActionRepository
from .search.storage.service import SearchService

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(
    store: GraphStore,
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
    include_legacy_routes: bool = True,
) -> "FastAPI":
    """Create the ontology FastAPI application."""

    from fastapi import FastAPI

    from .action.api.legacy_router import create_legacy_router
    from .action.api.router import create_router as create_action_router
    from .search.api.router import create_router as create_search_router

    app = FastAPI(title="Ontology API")
    instance_service = InstanceService(store)
    search_service = SearchService(instance_service)

    app.include_router(
        create_action_router(
            action_service=action_service,
            repository=repository,
        ),
        prefix="/api/v1",
    )
    app.include_router(create_search_router(search_service), prefix="/api/v1")

    if include_legacy_routes:
        app.include_router(
            create_legacy_router(
                action_service=action_service,
                repository=repository,
            )
        )

    return app


__all__ = ["create_app"]
