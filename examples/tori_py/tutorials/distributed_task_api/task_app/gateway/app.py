"""Client-only HTTP gateway and production composition root."""

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

from ..contracts import CreateTaskV1, Task, TaskService
from ..infrastructure import rabbitmq_url


@controller("/tasks")
class GatewayController:
    def __init__(self, tasks: TaskService) -> None:
        self._tasks = tasks

    @post("")
    @status(201)
    async def create(
        self,
        body: Annotated[CreateTaskV1, Body()],
    ) -> Task:
        return await self._tasks.create_task(body.title)

    @get("")
    async def list(self) -> list[Task]:
        return await self._tasks.list_tasks()

    @get("/{task_id}")
    async def get_one(
        self,
        task_id: Annotated[int, Path("task_id")],
    ) -> Task:
        return await self._tasks.get_task(task_id)


class GatewayErrorFilter:
    """Translate expected RPC failures without exposing internal exceptions."""

    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        title: str | None = None
        headers: dict[str, str] | None = None
        errors: object | None = None

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
            }.get(error.code, 502)
            detail = error.message
        elif isinstance(error, UnknownServiceError):
            status_code = 503
            detail = "The task service is unavailable."
        elif isinstance(error, RpcTimeoutError):
            status_code = 504
            detail = "The task service request timed out."
        elif isinstance(error, (RpcOutcomeUnknownError, TransportIndeterminateError)):
            status_code = 502
            detail = "The task service request outcome is unknown."
        elif isinstance(error, TransportTimeoutError):
            status_code = 504
            detail = "The service transport operation timed out."
        elif isinstance(error, RpcProtocolError):
            status_code = 502
            detail = "The task service returned an invalid response."
        elif isinstance(error, (RabbitMqConnectionError, TransportError)):
            status_code = 503
            detail = "The service transport is unavailable."
        elif isinstance(error, RpcClientError):
            status_code = 502
            detail = "The task service request failed."
        else:
            status_code = 500
            detail = "The gateway could not complete the request."

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
        rabbitmq_url(),
        connection_name="distributed-task-gateway",
    )
)
gateway_clients = ClientsModule.register_cluster(
    gateway_transport,
    imports=(gateway_rabbit,),
    contracts=(TaskService,),
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
    """HTTP-only root with a typed task client and no service runtime."""


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
