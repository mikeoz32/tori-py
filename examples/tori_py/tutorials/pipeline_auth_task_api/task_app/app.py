"""Module composition and ASGI bootstrap for the protected Task API."""

from tori_py import (
    ClassProvider,
    FactoryProvider,
    NestApplication,
    PipelineOptions,
    Scope,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi

from .audit import AuditInterceptor, AuditLog
from .auth import (
    AuthenticationGuard,
    CurrentPrincipal,
    DemoTokenVerifier,
    RequireAdmin,
    RequireUser,
    TokenVerifier,
)
from .http import AuditController, TaskController, TaskErrorFilter
from .maintenance import MaintenanceMiddleware, MaintenanceMode
from .services import TaskService
from .state import TaskRepository


@module(
    providers=[ClassProvider(TaskRepository)],
    exports=[TaskRepository],
)
class InfrastructureModule:
    pass


@module(
    providers=[
        ClassProvider(TokenVerifier, DemoTokenVerifier),
        ClassProvider(CurrentPrincipal, scope=Scope.REQUEST),
        ClassProvider(AuthenticationGuard, scope=Scope.REQUEST),
        ClassProvider(RequireUser, scope=Scope.REQUEST),
        ClassProvider(RequireAdmin, scope=Scope.REQUEST),
    ],
    exports=[
        TokenVerifier,
        CurrentPrincipal,
        AuthenticationGuard,
        RequireUser,
        RequireAdmin,
    ],
)
class AuthModule:
    pass


@module(
    imports=[AuthModule],
    providers=[
        ClassProvider(AuditLog),
        ClassProvider(AuditInterceptor, scope=Scope.REQUEST),
    ],
    exports=[AuditLog, AuditInterceptor],
)
class AuditModule:
    pass


@module(
    imports=[InfrastructureModule, AuthModule, AuditModule],
    providers=[ClassProvider(TaskService)],
    controllers=[TaskController, AuditController],
)
class TasksModule:
    pass


@module(
    imports=[TasksModule],
    providers=[
        FactoryProvider(MaintenanceMode, MaintenanceMode.from_environment),
        ClassProvider(MaintenanceMiddleware),
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("task-errors", TaskErrorFilter()),
    ],
)
class AppModule:
    pass


PIPELINE = PipelineOptions(
    middleware=(MaintenanceMiddleware,),
    pipes=("validation",),
    filters=("task-errors",),
)


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AppModule,
        adapter=StarletteAdapter(),
        pipeline=PIPELINE,
    )


application = asgi(create_application)
