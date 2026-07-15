"""FastAPI application lifecycle and CQRS dependency helpers."""

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import cast

from cqrs_core.builder import CqrsBuses
from cqrs_core.buses import CommandBus, EventBus, QueryBus
from fastapi import FastAPI, Request

logger = logging.getLogger(__name__)


class FastAPIConfigurationError(RuntimeError):
    """Raised when a FastAPI app has not been initialized with CQRS buses."""


type BusesFactory = Callable[[], CqrsBuses | Awaitable[CqrsBuses]]


@dataclass(slots=True)
class _AppCqrsState:
    buses: CqrsBuses
    ready: bool = False


class FastAPIAdapter:
    """Bind one lazily-built CQRS graph to one FastAPI application."""

    def __init__(
        self,
        buses_factory: BusesFactory,
        *,
        provider: object | None = None,
        shutdown_timeout: float | None = None,
    ) -> None:
        self._buses_factory = buses_factory
        self._provider = provider
        self._shutdown_timeout = shutdown_timeout
        self._lock = asyncio.Lock()
        self._lifespan_active = False
        self._lifespan_used = False

    async def get_buses(self, app: FastAPI) -> CqrsBuses:
        """Build or return the one CQRS graph associated with ``app``."""

        state = getattr(app.state, "cqrs", None)
        if isinstance(state, _AppCqrsState):
            return state.buses

        async with self._lock:
            state = getattr(app.state, "cqrs", None)
            if isinstance(state, _AppCqrsState):
                return state.buses
            result = self._buses_factory()
            if inspect.isawaitable(result):
                buses = await cast(Awaitable[CqrsBuses], result)
            else:
                buses = cast(CqrsBuses, result)
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

        try:
            buses = await self.get_buses(app)
            if self._provider is not None:
                bind_app = getattr(self._provider, "bind_app", None)
                if callable(bind_app):
                    bind_app(app)
        except BaseException:
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

        if self._provider is not None:
            close = getattr(self._provider, "close", None)
            if callable(close):
                try:
                    result = close(timeout=_remaining(deadline))
                    if inspect.isawaitable(result):
                        await result
                except BaseException as error:
                    if first_error is None:
                        first_error = error
                    logger.exception("Failed to close CQRS handler provider")
        return first_error


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
