import asyncio
import json
from typing import Any, cast

import pytest
from nestpy.testing import http_client

from examples.nestpy.getting_started.asgi_wrapper.app import application as asgi_app
from examples.nestpy.getting_started.async_factory.app import (
    create_application as async_factory_application,
)
from examples.nestpy.getting_started.cli_run.app import (
    create_application as cli_application,
)
from examples.nestpy.getting_started.first_provider.app import (
    create_application as provider_application,
)
from examples.nestpy.getting_started.first_settings.app import (
    create_application as settings_application,
)
from examples.nestpy.getting_started.hello_world.app import (
    application as hello_asgi_app,
)
from examples.nestpy.getting_started.hello_world.app import (
    create_application as hello_application,
)
from examples.nestpy.getting_started.project_structure.app import (
    create_application as project_application,
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("factory", "path", "expected"),
    [
        (hello_application, "/hello", {"message": "Hello, Nestpy!"}),
        (
            async_factory_application,
            "/status",
            {"status": "ready after lifespan startup"},
        ),
        (
            cli_application,
            "/greeting",
            {"message": "Serve factories with nestpy run."},
        ),
        (
            project_application,
            "/project/message",
            {"message": "Keep module composition explicit."},
        ),
        (
            provider_application,
            "/greeting",
            {"message": "Providers are explicit constructor dependencies."},
        ),
        (
            settings_application,
            "/greeting",
            {"message": "Hello from settings"},
        ),
    ],
)
async def test_getting_started_http_examples(
    factory,
    path,
    expected,
) -> None:
    application = await factory()
    await application.start()
    try:
        async with http_client(application) as client:
            response = await client.get(path)
    finally:
        await application.shutdown()
    assert response.status_code == 200
    assert response.json() == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("application", "path", "expected"),
    [
        (hello_asgi_app, "/hello", {"message": "Hello, Nestpy!"}),
        (asgi_app, "/health", {"status": "ok"}),
    ],
)
async def test_asgi_wrapper_examples_serve_after_lifespan(
    application,
    path,
    expected,
    call_http,
    message_body,
) -> None:
    messages: list[dict[str, object]] = []
    events: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    startup_complete = asyncio.Event()

    async def receive() -> dict[str, object]:
        return await events.get()

    async def send(message: dict[str, object]) -> None:
        messages.append(message)
        if message["type"] == "lifespan.startup.complete":
            startup_complete.set()

    lifespan = asyncio.create_task(
        application(cast(Any, {"type": "lifespan"}), receive, send)
    )
    await events.put({"type": "lifespan.startup"})
    await startup_complete.wait()
    response = await call_http(application, path=path)
    await events.put({"type": "lifespan.shutdown"})
    await lifespan
    assert [message["type"] for message in messages] == [
        "lifespan.startup.complete",
        "lifespan.shutdown.complete",
    ]
    assert response[0]["status"] == 200
    assert json.loads(message_body(response[1])) == expected
