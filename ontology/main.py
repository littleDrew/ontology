"""Top-level application entrypoints for ontology."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from .action.api.service import ActionService
from .action.storage.repository import ActionRepository
from .instance.api.service import InstanceService
from .instance.storage.graph_store import GraphStore, InMemoryGraphStore
from .search.api.service import SearchService
from .object_monitor.api.service import InMemoryMonitorReleaseService
from .object_monitor.runtime.event_filter import EventFilter

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(
    store: GraphStore,
    action_service: ActionService | None = None,
    repository: ActionRepository | None = None,
    include_legacy_routes: bool = True,
) -> "FastAPI":
    """Build FastAPI app with phase-1 routers and shared services."""

    from fastapi import FastAPI
    from fastapi.responses import RedirectResponse

    from .action.api.legacy_router import create_legacy_router
    from .action.api.router import create_router as create_action_router
    from .search.api.router import create_router as create_search_router
    from .object_monitor.api.router import create_router as create_monitor_router

    app = FastAPI(title="Ontology API")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        """Redirect root path to interactive API docs."""

        return RedirectResponse(url="/docs", status_code=307)

    instance_service = InstanceService(store)
    search_service = SearchService(instance_service)
    monitor_release_service = InMemoryMonitorReleaseService()
    monitor_event_filter = EventFilter()

    app.include_router(
        create_action_router(
            action_service=action_service,
            repository=repository,
        ),
        prefix="/api/v1",
    )
    app.include_router(create_search_router(search_service), prefix="/api/v1")
    app.include_router(
        create_monitor_router(monitor_release_service, monitor_event_filter),
        prefix="/api/v1",
    )

    if include_legacy_routes:
        app.include_router(
            create_legacy_router(
                action_service=action_service,
                repository=repository,
            )
        )

    return app


def main() -> None:
    """Run ontology FastAPI server with an in-memory graph store."""

    parser = argparse.ArgumentParser(description="Run ontology backend server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen on")
    parser.add_argument(
        "--no-legacy-routes",
        action="store_true",
        help="Disable legacy /actions routes",
    )
    args = parser.parse_args()

    import uvicorn

    app = create_app(
        store=InMemoryGraphStore(),
        include_legacy_routes=not args.no_legacy_routes,
    )
    uvicorn.run(app, host=args.host, port=args.port)


__all__ = ["create_app", "main"]


if __name__ == "__main__":
    main()
