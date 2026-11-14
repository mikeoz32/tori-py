from __future__ import annotations

import asyncio
import secrets
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Annotated, Any

import httpx
import pytest
import uvicorn
from tori_py import ClassProvider, Inject, injectable, module
from tori_py.starlette import ASGIApplication
from tori_py_liveview import LiveViewConfigurationError, live_view
from tori_py_liveview_kit import (
    AssistantMessage,
    ChatLiveView,
    Message,
    TextPart,
    UserMessage,
    create_app,
    run_app,
)
from tori_py_liveview_ui import SCRIPT_PATH, STYLESHEET_PATH


@live_view("/")
class EchoLive(ChatLiveView):
    welcome = "Say something"
    flush_interval = 0.0
    pages: list[EchoLive] = []

    async def mount(self, context) -> None:
        await super().mount(context)
        if context.connected:
            EchoLive.pages.append(self)

    async def respond(self, messages: Sequence[Message]):
        last = messages[-1]
        assert isinstance(last, UserMessage)
        yield f"You said: {last.text}"


@injectable()
class Greeter:
    def greeting(self) -> str:
        return "Hello from a provider"


class Clock:
    def now(self) -> str:
        return "noon"


@module(providers=[Greeter], exports=[Greeter])
class GreeterModule:
    pass


@live_view("/greeting")
class GreetingLive(ChatLiveView):
    def __init__(
        self,
        greeter: Annotated[Greeter, Inject(Greeter)],
        clock: Annotated[Clock, Inject(Clock)],
    ) -> None:
        self.welcome = f"{greeter.greeting()} at {clock.now()}"

    async def respond(self, messages: Sequence[Message]):
        yield "unused"


@asynccontextmanager
async def _started(application: ASGIApplication) -> AsyncIterator[httpx.AsyncClient]:
    """Run the application's lifespan, as an ASGI server does."""
    incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    outgoing: asyncio.Queue[Any] = asyncio.Queue()
    scope: Any = {"type": "lifespan", "asgi": {"version": "3.0"}}
    lifespan = asyncio.ensure_future(application(scope, incoming.get, outgoing.put))
    await incoming.put({"type": "lifespan.startup"})
    started = await asyncio.wait_for(outgoing.get(), timeout=5)
    assert started == {"type": "lifespan.startup.complete"}, started
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://testserver",
        ) as client:
            yield client
    finally:
        await incoming.put({"type": "lifespan.shutdown"})
        await asyncio.wait_for(lifespan, timeout=10)


@pytest.mark.asyncio
async def test_create_app_serves_the_page_the_client_and_the_ui_assets() -> None:
    application = create_app(EchoLive)

    assert isinstance(application, ASGIApplication)
    async with _started(application) as client:
        page = await client.get("/")
        assert page.status_code == 200
        assert "Say something" in page.text
        assert f'href="{STYLESHEET_PATH}"' in page.text
        assert f'src="{SCRIPT_PATH}"' in page.text
        for path in (STYLESHEET_PATH, SCRIPT_PATH, "/_tori/live.js"):
            assert (await client.get(path)).status_code == 200


@pytest.mark.asyncio
async def test_a_browser_can_chat_with_a_created_app(open_channel) -> None:
    EchoLive.pages = []
    application = create_app(EchoLive)

    async with _started(application):
        channel = open_channel(application, "/")
        await channel.join()
        page = EchoLive.pages[-1]
        await channel.event("chat:send", {"message": "hello"})
        await channel.until(lambda: not page.busy)

        assert page.messages[-1] == AssistantMessage(
            "turn-1-assistant", (TextPart("You said: hello"),)
        )
        assert "You said: hello" in channel.html(-1)
        await channel.close()


def test_create_app_generates_a_secret_unless_one_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated: list[int] = []

    def token_urlsafe(size: int) -> str:
        generated.append(size)
        return "g" * 64

    monkeypatch.setattr(secrets, "token_urlsafe", token_urlsafe)

    create_app(EchoLive)
    assert generated == [48]
    create_app(EchoLive, secret="s" * 32)
    assert generated == [48]
    # A secret that is too short is refused, not replaced.
    with pytest.raises(LiveViewConfigurationError, match="at least 32 bytes"):
        create_app(EchoLive, secret="short")
    with pytest.raises(LiveViewConfigurationError, match="at least 32 bytes"):
        create_app(EchoLive, secret="")


def test_create_app_needs_a_page() -> None:
    with pytest.raises(LiveViewConfigurationError, match="at least one LiveView page"):
        create_app()


@pytest.mark.asyncio
async def test_create_app_gives_pages_their_constructor_dependencies() -> None:
    application = create_app(
        GreetingLive, providers=[ClassProvider(Clock)], imports=[GreeterModule]
    )

    async with _started(application) as client:
        page = await client.get("/greeting")

    assert page.status_code == 200
    assert "Hello from a provider at noon" in page.text


@pytest.mark.asyncio
async def test_create_app_accepts_injectable_classes_as_providers() -> None:
    application = create_app(GreetingLive, providers=[Greeter, ClassProvider(Clock)])

    async with _started(application) as client:
        page = await client.get("/greeting")

    assert "Hello from a provider at noon" in page.text


def test_run_app_serves_on_the_loopback_interface_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, dict[str, object]]] = []
    monkeypatch.setattr(
        uvicorn,
        "run",
        lambda application, **options: calls.append((application, options)),
    )

    run_app(EchoLive)
    run_app(EchoLive, host="0.0.0.0", port=9000, secret="s" * 32)

    assert [options for _, options in calls] == [
        {"host": "127.0.0.1", "port": 8000, "lifespan": "on"},
        {"host": "0.0.0.0", "port": 9000, "lifespan": "on"},
    ]
    assert all(isinstance(application, ASGIApplication) for application, _ in calls)
