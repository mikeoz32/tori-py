"""Async factory for the project structure example."""

from tori_py import NestApplication
from tori_py.starlette import StarletteAdapter

from examples.tori_py.getting_started.project_structure.modules import AppModule


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())
