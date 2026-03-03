"""Top-level application entrypoints for ontology.

This module provides a stable, root-level API constructor while keeping
HTTP routing implementation inside ``ontology.action.api``.
"""

from __future__ import annotations

from .action.api import create_app as _create_action_app


def create_app(*args, **kwargs):
    """Create the ontology FastAPI application.

    Delegates to ``ontology.action.api.create_app`` so callers can use a
    simple root-level import path: ``from ontology.main import create_app``.
    """

    return _create_action_app(*args, **kwargs)


__all__ = ["create_app"]
