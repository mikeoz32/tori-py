"""CQRS graph assembly and Nestpy lifecycle coordination."""

from __future__ import annotations

import inspect
import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from enum import StrEnum

from cqrs_core import (
    CommandBus,
    CqrsBuilder,
    CqrsBuses,
    EventBus,
    EventErrorHandler,
    EventHandlerFailure,
    HandlerKind,
    QueryBus,
    Transport,
)
from nestpy import ShutdownContext

from nestpy_cqrs.errors import CqrsConfigurationError, CqrsLifecycleError
from nestpy_cqrs.options import CqrsModuleOptions, TransportFactory
from nestpy_cqrs.provider import NestpyHandlerProvider, _BindingPlan

logger = logging.getLogger(__name__)


class _RuntimeState(StrEnum):
    NEW = "new"
    RUNNING = "running"
    STOPPED = "stopped"


class _CqrsRuntime:
    def __init__(self, buses: CqrsBuses) -> None:
        self.buses = buses
        self._state = _RuntimeState.NEW

    async def on_application_bootstrap(self) -> None:
        attempted: list[CommandBus | QueryBus | EventBus] = []
        try:
            for bus in (
                self.buses.event_bus,
                self.buses.query_bus,
                self.buses.command_bus,
            ):
                attempted.append(bus)
                await bus.start()
        except BaseException as error:
            control_error = error if not isinstance(error, Exception) else None
            for bus in reversed(attempted):
                try:
                    await bus.shutdown(timeout=0)
                except BaseException as cleanup_error:
                    if control_error is None and not isinstance(
                        cleanup_error, Exception
                    ):
                        control_error = cleanup_error
                    elif isinstance(cleanup_error, Exception):
                        _log_cleanup_failure(
                            "CQRS startup rollback cleanup failed",
                            cleanup_error,
                        )
            self._state = _RuntimeState.STOPPED
            if control_error is not None:
                if control_error is error:
                    raise
                raise control_error from error
            raise CqrsLifecycleError("CQRS bus startup failed") from error
        self._state = _RuntimeState.RUNNING

    async def on_application_quiesce(self, context: ShutdownContext) -> None:
        if self._state is _RuntimeState.STOPPED:
            return
        first_error: Exception | None = None
        for bus in (
            self.buses.command_bus,
            self.buses.query_bus,
            self.buses.event_bus,
        ):
            try:
                await bus.shutdown(timeout=context.remaining())
            except Exception as error:
                if first_error is None:
                    first_error = error
                else:
                    _log_cleanup_failure("CQRS bus shutdown failed", error)
            except BaseException:
                if first_error is not None:
                    _log_cleanup_failure(
                        "CQRS quiesce failure suppressed by control flow",
                        first_error,
                    )
                raise
        self._state = _RuntimeState.STOPPED
        if first_error is not None:
            raise CqrsLifecycleError("CQRS bus shutdown failed") from first_error

    async def close(self) -> None:
        ordinary_errors: list[Exception] = []
        control_error: BaseException | None = None
        for bus in (
            self.buses.command_bus,
            self.buses.query_bus,
            self.buses.event_bus,
        ):
            try:
                await bus.shutdown(timeout=0)
            except BaseException as error:
                if not isinstance(error, Exception):
                    if control_error is None:
                        control_error = error
                else:
                    ordinary_errors.append(error)
        self._state = _RuntimeState.STOPPED
        if control_error is not None:
            for error in ordinary_errors:
                _log_cleanup_failure("CQRS fallback cleanup failed", error)
            raise control_error
        if ordinary_errors:
            for error in ordinary_errors[1:]:
                _log_cleanup_failure("CQRS fallback cleanup failed", error)
            raise ordinary_errors[0]


async def _transport(factory: TransportFactory, name: str) -> Transport:
    try:
        transport = factory()
        if inspect.isawaitable(transport):
            transport = await transport
    except Exception as error:
        raise CqrsConfigurationError(f"{name} transport factory failed") from error
    if not isinstance(transport, Transport):
        raise CqrsConfigurationError(
            f"{name} transport factory must return a Transport"
        )
    return transport


def _create_runtime(
    options: CqrsModuleOptions,
    provider: NestpyHandlerProvider,
    plan: _BindingPlan,
) -> AbstractAsyncContextManager[_CqrsRuntime]:
    @asynccontextmanager
    async def managed() -> AsyncIterator[_CqrsRuntime]:
        transports: list[Transport] = []
        runtime: _CqrsRuntime | None = None
        active_control: BaseException | None = None
        try:
            command_transport = await _transport(
                options.command_transport_factory,
                "command",
            )
            transports.append(command_transport)
            query_transport = await _transport(options.query_transport_factory, "query")
            transports.append(query_transport)
            event_transport = await _transport(options.event_transport_factory, "event")
            transports.append(event_transport)
            builder = (
                CqrsBuilder()
                .with_command_transport(command_transport)
                .with_query_transport(query_transport)
                .with_event_transport(event_transport)
                .with_handler_provider(provider)
            )
            if options.event_error_handler is not None:
                builder.with_event_error_handler(
                    _map_event_error_handler(options, plan)
                )
            for entry in plan.entries:
                if entry.kind is HandlerKind.COMMAND:
                    builder.add_command_handler_factory(
                        entry.message_type, entry.marker
                    )
                elif entry.kind is HandlerKind.QUERY:
                    builder.add_query_handler_factory(entry.message_type, entry.marker)
                else:
                    builder.add_event_handler_factory(entry.message_type, entry.marker)
            runtime = _CqrsRuntime(builder.build())
            yield runtime
        except BaseException as error:
            if not isinstance(error, Exception):
                active_control = error
            raise
        finally:
            if runtime is not None:
                try:
                    await runtime.close()
                except BaseException as cleanup_error:
                    if active_control is None:
                        raise
                    if isinstance(cleanup_error, Exception):
                        _log_cleanup_failure(
                            "CQRS managed runtime cleanup failed",
                            cleanup_error,
                        )
            else:
                control_error: BaseException | None = None
                for transport in _reverse_unique(transports):
                    try:
                        await transport.shutdown(timeout=0)
                    except BaseException as error:
                        if control_error is None and not isinstance(error, Exception):
                            control_error = error
                        elif isinstance(error, Exception):
                            _log_cleanup_failure(
                                "CQRS transport cleanup failed",
                                error,
                            )
                if control_error is not None and active_control is None:
                    raise control_error

    return managed()


def _reverse_unique(transports: list[Transport]) -> tuple[Transport, ...]:
    seen: set[int] = set()
    unique: list[Transport] = []
    for transport in reversed(transports):
        identity = id(transport)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(transport)
    return tuple(unique)


def _log_cleanup_failure(message: str, error: Exception) -> None:
    logger.error(
        message,
        exc_info=(type(error), error, error.__traceback__),
    )


def _map_event_error_handler(
    options: CqrsModuleOptions,
    plan: _BindingPlan,
) -> EventErrorHandler:
    error_handler = options.event_error_handler
    assert error_handler is not None

    async def mapped(failure: EventHandlerFailure) -> None:
        handler, handler_id = plan.failure_identity(failure.handler_id)
        result = error_handler(
            EventHandlerFailure(
                error=failure.error,
                envelope=failure.envelope,
                handler=handler,
                handler_id=handler_id,
            )
        )
        if inspect.isawaitable(result):
            await result

    return mapped


def _buses(runtime: _CqrsRuntime) -> CqrsBuses:
    return runtime.buses


def _command_bus(runtime: _CqrsRuntime) -> CommandBus:
    return runtime.buses.command_bus


def _query_bus(runtime: _CqrsRuntime) -> QueryBus:
    return runtime.buses.query_bus


def _event_bus(runtime: _CqrsRuntime) -> EventBus:
    return runtime.buses.event_bus


__all__: list[str] = []
