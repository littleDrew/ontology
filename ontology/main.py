"""Top-level application entrypoints for ontology."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .action.api.service import ActionService
from .action.storage.graph_store import GraphStore
from .action.storage.repository import ActionRepository

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(
    store: GraphStore,
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
) -> "FastAPI":
    """Create the ontology FastAPI application.

    The app is composed from feature routers via ``include_router`` so that
    new modules (e.g. define/search) can be added without bloating this file.
    """

    from fastapi import FastAPI

    from .action.api.router import create_router

    app = FastAPI(title="Ontology API")
    app.include_router(
        create_router(
            store=store,
            action_service=action_service,
            repository=repository,
        )
    )
    return app


__all__ = ["create_app"]
