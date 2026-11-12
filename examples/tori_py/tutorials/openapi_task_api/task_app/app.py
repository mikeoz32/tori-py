"""Module composition and ASGI bootstrap for the documented Task API."""

from tori_py import ClassProvider, NestApplication, ValueProvider, module
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_openapi import (
    BearerSecurityScheme,
    OpenApiInfo,
    OpenApiModule,
    OpenApiOptions,
    SwaggerUiOptions,
)

from .http import TaskController, TaskErrorFilter
from .services import TaskService
from .state import TaskRepository


@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
)
class InfrastructureModule:
    pass


@module(
    imports=[InfrastructureModule],
    providers=[ClassProvider(TaskService)],
    controllers=[TaskController],
)
class TasksModule:
    pass


openapi_module = OpenApiModule.for_root(
    OpenApiOptions(
        info=OpenApiInfo(
            title="Task API",
            version="1.0.0",
            description="Create, read, and delete tasks.",
        ),
        security_schemes=(
            BearerSecurityScheme(
                "admin",
                bearer_format=None,
                description="Administrator token",
            ),
        ),
        swagger_ui=SwaggerUiOptions(parameters={"persistAuthorization": True}),
    )
)


@module(
    imports=[TasksModule, openapi_module],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    pass


async def create_application() -> NestApplication:
    app = await NestApplication.create(AppModule, adapter=StarletteAdapter())
    app.use_global_pipe("validation")
    app.use_global_filter("task-errors")
    return app


application = asgi(create_application)
