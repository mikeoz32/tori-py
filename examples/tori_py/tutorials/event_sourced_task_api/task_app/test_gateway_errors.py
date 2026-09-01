"""Focused command-error and gateway Problem Details assertions."""

from __future__ import annotations

import json
from typing import cast

import pytest
from starlette.requests import Request
from starlette.responses import Response
from tori_py.http import HttpException
from tori_py.starlette import RequestContext
from tori_py_cqrs_event_sourcing import (
    CommandFinalizationPhase,
    ConfirmedNonCommitFinalizationError,
)
from tori_py_cqrs_event_sourcing_core import (
    CommitResultMismatchError,
    ConfirmedNonCommit,
)
from tori_py_microservices import (
    PublicRpcError,
    RemoteRpcError,
    RpcTimeoutError,
    UnknownServiceError,
)

from .contracts import CreateTaskV1
from .gateway.app import GatewayErrorFilter
from .tasks.app import TaskRpcController
from .tasks.relay import RelayPublicationError, RelayUnavailable
from .tasks.services import TaskApplicationService


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "code", "retryable"),
    (
        (RelayUnavailable("unavailable"), "relay_unavailable", False),
        (RelayPublicationError("stopped"), "relay_unavailable", False),
        (CommitResultMismatchError("mismatch"), "command_outcome_unknown", False),
        (
            ConfirmedNonCommitFinalizationError(
                outcome=ConfirmedNonCommit(RuntimeError("not committed")),
                phase=CommandFinalizationPhase.SCOPE_CLEANUP,
                primary_error=RuntimeError("cleanup failed"),
            ),
            "command_finalization_failed",
            False,
        ),
    ),
)
async def test_task_rpc_maps_hardened_command_failures(
    error: Exception,
    code: str,
    retryable: bool,
) -> None:
    controller = TaskRpcController(
        cast(TaskApplicationService, _FailingTaskService(error))
    )
    with pytest.raises(PublicRpcError) as captured:
        await controller.create_task(CreateTaskV1("Title"))
    assert captured.value.code == code
    assert captured.value.retryable is retryable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status", "title"),
    (
        (
            RemoteRpcError("conflict", "Conflict detail", retryable=False),
            409,
            "Conflict",
        ),
        (
            RemoteRpcError("internal", "Upstream detail", retryable=False),
            502,
            "Bad Gateway",
        ),
        (HttpException(409, "HTTP conflict"), 409, "Conflict"),
        (
            HttpException(409, "HTTP conflict", title="Task Conflict"),
            409,
            "Task Conflict",
        ),
        (RuntimeError("unexpected"), 500, "Internal Server Error"),
        (
            RemoteRpcError(
                "relay_unavailable",
                "Task event relay is unavailable.",
                retryable=False,
            ),
            503,
            "Service Unavailable",
        ),
        (UnknownServiceError("missing"), 503, "Service Unavailable"),
        (RpcTimeoutError("timeout"), 504, "Gateway Timeout"),
    ),
)
async def test_gateway_uses_standard_problem_titles(
    error: Exception,
    status: int,
    title: str,
) -> None:
    body = await _problem(error)
    assert body["status"] == status
    assert body["title"] == title


@pytest.mark.asyncio
async def test_gateway_command_timeout_warns_that_outcome_may_be_unknown() -> None:
    body = await _problem(RpcTimeoutError("timeout"))
    assert body["detail"] == (
        "The task command request timed out; its outcome may be unknown."
    )


async def _problem(error: Exception) -> dict[str, object]:
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/tasks",
            "raw_path": b"/tasks",
            "query_string": b"",
            "headers": (),
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )
    context = cast(RequestContext, _GatewayContext(request))
    result = await GatewayErrorFilter().catch(error, context)
    response = cast(Response, result.value)
    return cast(dict[str, object], json.loads(bytes(response.body)))


class _FailingTaskService:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def create(self, title: str):
        del title
        raise self._error

    async def rename(self, task_id: int, title: str):
        del task_id, title
        raise self._error


class _GatewayContext:
    def __init__(self, request: Request) -> None:
        self.request = request
