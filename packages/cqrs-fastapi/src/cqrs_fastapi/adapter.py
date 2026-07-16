"""FastAPI application lifecycle and CQRS dependency helpers."""

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from cqrs_core.builder import CqrsBuilder, CqrsBuses
from cqrs_core.buses import CommandBus, EventBus, EventErrorHandler, QueryBus
from cqrs_core.inmemory import InMemoryTransport
from cqrs_core.messages import Message
from cqrs_core.protocols import HandlerProvider, Transport
from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)


class FastAPIConfigurationError(RuntimeError):
    """Raised when a FastAPI app has not been initialized with CQRS buses."""


type BusesReadyHook = Callable[[CqrsBuses], object | Awaitable[object]]


@dataclass(slots=True)
class _AppCqrsState:
    buses: CqrsBuses
    ready: bool = False


class FastAPIAdapter:
    """Bind one lazily-built CQRS graph to one FastAPI application."""

    def __init__(
        self,
        *,
        command_transport: Transport | None = None,
        query_transport: Transport | None = None,
        event_transport: Transport | None = None,
        provider: HandlerProvider[object] | None = None,
        event_error_handler: EventErrorHandler | None = None,
        on_buses_built: BusesReadyHook | None = None,
        shutdown_timeout: float | None = None,
    ) -> None:
        self._builder = CqrsBuilder()
        self._builder.with_command_transport(
            command_transport
            if command_transport is not None
            else InMemoryTransport(name="fastapi-command")
        )
        self._builder.with_query_transport(
            query_transport
            if query_transport is not None
            else InMemoryTransport(name="fastapi-query")
        )
        self._builder.with_event_transport(
            event_transport
            if event_transport is not None
            else InMemoryTransport(name="fastapi-event")
        )
        if provider is not None:
            self._builder.with_handler_provider(provider)
        if event_error_handler is not None:
            self._builder.with_event_error_handler(event_error_handler)
        self._on_buses_built = on_buses_built
        self._provider = provider
        self._shutdown_timeout = shutdown_timeout
        self._lock = asyncio.Lock()
        self._lifespan_active = False
        self._lifespan_used = False

    def command_handler(self, message_type: type[Message]):
        """Register a command handler through an adapter decorator."""

        def decorate(target: object) -> object:
            self._builder.add_command_handler(message_type, target)
            return target

        return decorate

    def query_handler(self, message_type: type[Message]):
        """Register a query handler through an adapter decorator."""

        def decorate(target: object) -> object:
            self._builder.add_query_handler(message_type, target)
            return target

        return decorate

    def event_handler(self, message_type: type[Message]):
        """Register an event handler through an adapter decorator."""

        def decorate(target: object) -> object:
            self._builder.add_event_handler(message_type, target)
            return target

        return decorate

    def command_handler_factory(self, message_type: type[Message]):
        """Register a command handler factory through an adapter decorator."""

        def decorate(target: object) -> object:
            self._builder.add_command_handler_factory(message_type, target)
            return target

        return decorate

    def query_handler_factory(self, message_type: type[Message]):
        """Register a query handler factory through an adapter decorator."""

        def decorate(target: object) -> object:
            self._builder.add_query_handler_factory(message_type, target)
            return target

        return decorate

    def event_handler_factory(self, message_type: type[Message]):
        """Register an event handler factory through an adapter decorator."""

        def decorate(target: object) -> object:
            self._builder.add_event_handler_factory(message_type, target)
            return target

        return decorate

    async def get_buses(self, app: FastAPI) -> CqrsBuses:
        """Build or return the one CQRS graph associated with ``app``."""

        state = getattr(app.state, "cqrs", None)
        if isinstance(state, _AppCqrsState):
            return state.buses

        async with self._lock:
            state = getattr(app.state, "cqrs", None)
            if isinstance(state, _AppCqrsState):
                return state.buses
            buses = self._builder.build()
            try:
                if self._on_buses_built is not None:
                    result = self._on_buses_built(buses)
                    if inspect.isawaitable(result):
                        await result
            except BaseException:
                try:
                    await self._close_provider(timeout=self._shutdown_timeout)
                except BaseException:
                    logger.exception("Failed to close provider after build failure")
                raise
            app.state.cqrs = _AppCqrsState(buses=buses)
            app.state.cqrs_buses = buses
            app.state.cqrs_ready = False
            return buses

    @asynccontextmanager
    async def lifespan(self, app: FastAPI) -> AsyncIterator[None]:
        """Start all buses before serving and drain them during shutdown."""

        async with self._lock:
            if self._lifespan_active:
                raise RuntimeError("FastAPIAdapter lifespan is already active")
            if self._lifespan_used:
                raise RuntimeError("FastAPIAdapter lifespan cannot be reused")
            self._lifespan_active = True
            self._lifespan_used = True

        buses: CqrsBuses | None = None
        try:
            buses = await self.get_buses(app)
            if self._provider is not None:
                bind_app = getattr(self._provider, "bind_app", None)
                if callable(bind_app):
                    bind_app(app)
        except BaseException:
            try:
                if buses is not None:
                    await self._shutdown_components(buses)
                else:
                    await self._close_provider(timeout=self._shutdown_timeout)
            except BaseException:
                logger.exception("Failed to clean up after lifespan setup failure")
            async with self._lock:
                self._lifespan_active = False
            raise

        failure: BaseException | None = None
        try:
            await self._start_buses(buses)
            _set_ready(app, True)
            yield
        except BaseException as error:
            failure = error
        finally:
            _set_ready(app, False)
            cleanup_error = await self._shutdown_components(buses)
            _set_ready(app, False)
            async with self._lock:
                self._lifespan_active = False
            if failure is None and cleanup_error is not None:
                raise cleanup_error
        if failure is not None:
            raise failure

    async def _start_buses(self, buses: CqrsBuses) -> None:
        started: list[object] = []
        try:
            for bus in (buses.command_bus, buses.query_bus, buses.event_bus):
                started.append(bus)
                await bus.start()
        except BaseException:
            for bus in reversed(started):
                try:
                    await cast(CommandBus | QueryBus | EventBus, bus).shutdown(
                        timeout=self._shutdown_timeout
                    )
                except BaseException:
                    logger.exception("Failed to clean up bus after startup failure")
            raise

    async def _shutdown_components(self, buses: CqrsBuses) -> BaseException | None:
        deadline = _deadline(self._shutdown_timeout)
        first_error: BaseException | None = None
        for bus in (buses.command_bus, buses.query_bus, buses.event_bus):
            try:
                await bus.shutdown(timeout=_remaining(deadline))
            except BaseException as error:
                if first_error is None:
                    first_error = error
                logger.exception("Failed to shut down CQRS bus")

        try:
            await self._close_provider(timeout=_remaining(deadline))
        except BaseException as error:
            if first_error is None:
                first_error = error
            logger.exception("Failed to close CQRS handler provider")
        return first_error

    async def _close_provider(self, *, timeout: float | None) -> None:
        if self._provider is None:
            return
        close = getattr(self._provider, "close", None)
        if not callable(close):
            return
        result = close(timeout=timeout)
        if inspect.isawaitable(result):
            await result


def _set_ready(app: FastAPI, ready: bool) -> None:
    state = getattr(app.state, "cqrs", None)
    if isinstance(state, _AppCqrsState):
        state.ready = ready
    app.state.cqrs_ready = ready


def _require_bus_state(request: Request) -> CqrsBuses:
    state = getattr(request.app.state, "cqrs", None)
    if not isinstance(state, _AppCqrsState) or not state.ready:
        raise FastAPIConfigurationError(
            "CQRS buses are not ready; configure FastAPIAdapter as the app lifespan"
        )
    return state.buses


def get_command_bus(request: Request) -> CommandBus:
    """Return the configured command bus for the current app."""

    return _require_bus_state(request).command_bus


def get_query_bus(request: Request) -> QueryBus:
    """Return the configured query bus for the current app."""

    return _require_bus_state(request).query_bus


def get_event_bus(request: Request) -> EventBus:
    """Return the configured event bus for the current app."""

    return _require_bus_state(request).event_bus


def _deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    return asyncio.get_running_loop().time() + timeout


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - asyncio.get_running_loop().time())
