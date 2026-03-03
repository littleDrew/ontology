"""Action API package."""


def create_app(*args, **kwargs):
    from ...main import create_app as _create_app

    return _create_app(*args, **kwargs)


def create_router(*args, **kwargs):
    from .router import create_router as _create_router

    return _create_router(*args, **kwargs)


__all__ = ["create_app", "create_router"]
