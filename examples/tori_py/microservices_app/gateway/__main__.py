"""Run the gateway with Uvicorn-compatible ASGI application."""

from examples.tori_py.microservices_app.gateway.app import application

__all__ = ["application"]
