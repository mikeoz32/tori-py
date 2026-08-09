"""Run the gateway with Uvicorn-compatible ASGI application."""

from examples.nestpy.microservices_app.gateway.app import application

__all__ = ["application"]
