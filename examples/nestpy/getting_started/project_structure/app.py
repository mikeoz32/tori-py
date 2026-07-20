"""Async factory for the project structure example."""

from nestpy.starlette import NestApplication

from examples.nestpy.getting_started.project_structure.modules import AppModule


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule)
