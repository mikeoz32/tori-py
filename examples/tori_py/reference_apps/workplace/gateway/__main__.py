"""ASGI entry point."""

from .app import create_application


def application_factory() -> object:
    from tori_py.starlette import asgi

    return asgi(create_application)


application = application_factory()
