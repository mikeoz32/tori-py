"""HTTP gateway and production client-only composition root."""

from __future__ import annotations

from typing import Annotated

from tori_py import (
    Body,
    NestApplication,
    Path,
    PipelineOptions,
    PipelineResult,
    ValueProvider,
    controller,
    get,
    module,
    patch,
    post,
    status,
)
from tori_py.http import HttpException, MsgspecValidationPipe
from tori_py.starlette import RequestContext, StarletteAdapter, asgi
from tori_py.starlette.errors import problem_response
from tori_py_microservices import (
    ClientsModule,
    RabbitMqConnectionError,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    RemoteRpcError,
    RpcClientError,
    RpcOutcomeUnknownError,
    RpcProtocolError,
    RpcTimeoutError,
    TransportError,
    TransportIndeterminateError,
    TransportTimeoutError,
    UnknownServiceError,
)

from ..contracts import (
    CreateTaskV1,
    Task,
    TaskCommandService,
    TaskProjectionService,
)
from ..infrastructure import rabbitmq_amqp_url


@controller("/tasks")
class GatewayController:
    def __init__(
        self,
        commands: TaskCommandService,
        projection: TaskProjectionService,
    ) -> None:
        self._commands = commands
        self._projection = projection

    @post("")
    @status(201)
    async def create(
        self,
        body: Annotated[CreateTaskV1, Body()],
    ) -> Task:
        return await self._commands.create_task(body.title)

    @patch("/{task_id}")
    async def rename(
        self,
        task_id: Annotated[int, Path("task_id")],
        body: Annotated[CreateTaskV1, Body()],
    ) -> Task:
        return await self._commands.rename_task(task_id, body.title)

    @get("")
    async def list_tasks(self) -> list[Task]:
        return await self._projection.list_tasks()

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return await self._projection.get_task(task_id)


class GatewayErrorFilter:
    """Translate validation and typed RPC failures to problem details."""

    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        title: str | None = None
        headers: dict[str, str] | None = None
        errors: object | None = None
        projection_read = context.request.method == "GET"

        if isinstance(error, HttpException):
            status_code = error.status_code
            detail = error.detail
            title = error.title
            headers = error.headers
            errors = error.errors
        elif isinstance(error, RemoteRpcError):
            status_code = {
                "invalid_request": 400,
                "not_found": 404,
                "conflict": 409,
                "projection_unavailable": 503,
                "command_committed_finalization_failed": 502,
                "command_finalization_failed": 502,
                "command_outcome_unknown": 502,
            }.get(error.code, 502)
            detail = error.message
        elif isinstance(error, UnknownServiceError):
            status_code = 503
            detail = (
                "The task projection service is unavailable."
                if projection_read
                else "The task command service is unavailable."
            )
        elif isinstance(error, RpcTimeoutError):
            status_code = 504
            detail = (
                "The task projection request timed out."
                if projection_read
                else "The task command request timed out; its outcome may be unknown."
            )
        elif isinstance(error, (RpcOutcomeUnknownError, TransportIndeterminateError)):
            status_code = 502
            detail = (
                "The task projection request outcome is unknown."
                if projection_read
                else "The task command request outcome is unknown."
            )
        elif isinstance(error, TransportTimeoutError):
            status_code = 504
            detail = "The service transport operation timed out."
        elif isinstance(error, RpcProtocolError):
            status_code = 502
            detail = "A task service returned an invalid response."
        elif isinstance(error, (RabbitMqConnectionError, TransportError)):
            status_code = 503
            detail = "The service transport is unavailable."
        elif isinstance(error, RpcClientError):
            status_code = 502
            detail = "The task service request failed."
        else:
            status_code = 500
            detail = "The gateway could not complete the request."

        if title in {None, "HTTP Error"}:
            title = {
                409: "Conflict",
                500: "Internal Server Error",
                502: "Bad Gateway",
                503: "Service Unavailable",
                504: "Gateway Timeout",
            }.get(status_code)
        return PipelineResult.from_response(
            problem_response(
                status_code,
                detail,
                request=context.request,
                title=title,
                headers=headers,
                errors=errors,
            )
        )


gateway_transport = RabbitMqTransport()
gateway_rabbit = RabbitMqModule.for_root(
    RabbitMqOptions(
        rabbitmq_amqp_url(),
        connection_name="event-sourced-task-gateway",
    )
)
gateway_clients = ClientsModule.register_cluster(
    gateway_transport,
    imports=(gateway_rabbit,),
    contracts=(TaskCommandService, TaskProjectionService),
)


@module(
    imports=(gateway_clients,),
    providers=(
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("gateway-errors", GatewayErrorFilter()),
    ),
    controllers=(GatewayController,),
)
class GatewayAppModule:
    """The gateway's independent HTTP-only application root."""


gateway_pipeline = PipelineOptions(
    pipes=("validation",),
    filters=("gateway-errors",),
)


async def create_application() -> NestApplication:
    return await NestApplication.create(
        GatewayAppModule,
        adapter=StarletteAdapter(),
        pipeline=gateway_pipeline,
    )


application = asgi(create_application)


__all__ = [
    "GatewayAppModule",
    "GatewayController",
    "GatewayErrorFilter",
    "application",
    "create_application",
    "gateway_pipeline",
    "gateway_rabbit",
    "gateway_transport",
]
