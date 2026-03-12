"""Compatibility exports for legacy imports.

Runtime/server bootstrap implementations now live in `scripts.object_monitor.service_factory`.
Keep this module as a stable import path for tests and existing callers.
"""

from scripts.object_monitor.service_factory import (  # noqa: F401
    build_object_monitor_data_plane_app,
    build_object_monitor_data_plane_service,
    build_object_monitor_server_app,
    build_ontology_main_server_app,
)
