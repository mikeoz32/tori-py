"""Public driver-neutral CQRS invocation pipeline contracts."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from cqrs_core import DispatchContext, Envelope, HandlerKind, Message
from nestpy import (
    BootstrapError,
    ExecutionContext,
    ModuleId,
    ProviderRef,
    ScopeCancellationError,
    ScopedResolver,
    ScopeFinalizationError,
    Token,
    validate_token,
)

from nestpy_cqrs.errors import CqrsConfigurationError, CqrsPipelineStateError

type CqrsNext = Callable[[], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class CqrsScopeCompletion:
    """Invocation outcome observed after every scoped resource has closed."""

    result: object | None
    result_available: bool
    body_error: BaseException | None
    scope_error: ScopeFinalizationError | ScopeCancellationError | None


type CqrsCompletionMapper = Callable[
    [CqrsScopeCompletion, BaseException | None], BaseException | None
]


class CqrsInvocationCompletion:
    """Collect composable post-scope error mappers during an invocation."""

    __slots__ = ("_frozen", "_keys", "_mappers")

    def __init__(self) -> None:
        self._frozen = False
        self._keys: set[str] = set()
        self._mappers: list[CqrsCompletionMapper] = []

    def register(self, key: str, mapper: CqrsCompletionMapper) -> None:
        """Register one unique synchronous mapper before the chain returns."""

        if self._frozen:
            raise CqrsPipelineStateError("invocation completion is frozen")
        if not isinstance(key, str) or not key:
            raise CqrsPipelineStateError("completion mapper key must be non-empty")
        if key in self._keys:
            raise CqrsPipelineStateError(
                f"completion mapper key {key!r} is already registered"
            )
        if not callable(mapper) or inspect.iscoroutinefunction(mapper):
            raise CqrsPipelineStateError("completion mapper must be synchronous")
        self._keys.add(key)
        self._mappers.append(mapper)

    def _freeze(self) -> None:
        self._frozen = True

    def _apply(
        self,
        completion: CqrsScopeCompletion,
        error: BaseException | None,
    ) -> BaseException | None:
        current = error
        for mapper in reversed(self._mappers):
            mapped = mapper(completion, current)
            if inspect.isawaitable(mapped):
                close = getattr(mapped, "close", None)
                if callable(close):
                    close()
                raise CqrsPipelineStateError("completion mapper must be synchronous")
            if mapped is not None and not isinstance(mapped, BaseException):
                raise CqrsPipelineStateError(
                    "completion mapper must return an exception or None"
                )
            if current is not None and mapped is None:
                raise CqrsPipelineStateError(
                    "completion mapper cannot suppress an existing error"
                )
            current = mapped
        return current


class CqrsInvocationContext(ExecutionContext):
    """Nestpy execution context for one CQRS handler invocation."""

    __slots__ = (
        "_application_id",
        "_completion",
        "_dispatch_context",
        "_handler_kind",
        "_handler_exit_callbacks",
        "_handler_exited",
        "_handler_ref",
        "_metadata",
        "_owner_module",
        "_resolver",
    )

    def __init__(
        self,
        *,
        application_id: str,
        dispatch_context: DispatchContext,
        handler_kind: HandlerKind,
        handler_ref: ProviderRef,
        owner_module: ModuleId,
        resolver: ScopedResolver,
        completion: CqrsInvocationCompletion | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        self._application_id = application_id
        self._dispatch_context = dispatch_context
        self._handler_kind = handler_kind
        self._handler_exit_callbacks: list[Callable[[], None]] = []
        self._handler_exited = False
        self._handler_ref = handler_ref
        self._owner_module = owner_module
        self._resolver = resolver
        self._completion = completion or CqrsInvocationCompletion()
        self._metadata = MappingProxyType(dict(metadata or {}))

    @property
    def application_id(self) -> str:
        return self._application_id

    @property
    def module_id(self) -> str:
        return _module_label(self._owner_module)

    @property
    def route_id(self) -> None:
        return None

    @property
    def request_id(self) -> None:
        return None

    @property
    def resolver(self) -> ScopedResolver:
        return self._resolver

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._metadata

    @property
    def execution_kind(self) -> str:
        return "cqrs"

    @property
    def dispatch_context(self) -> DispatchContext:
        return self._dispatch_context

    @property
    def message(self) -> Message:
        return self.envelope.message

    @property
    def envelope(self) -> Envelope[Message]:
        return self._dispatch_context.envelope

    @property
    def handler_kind(self) -> HandlerKind:
        return self._handler_kind

    @property
    def handler_ref(self) -> ProviderRef:
        return self._handler_ref

    @property
    def owner_module(self) -> ModuleId:
        return self._owner_module

    @property
    def completion(self) -> CqrsInvocationCompletion:
        return self._completion

    def on_handler_exit(self, callback: Callable[[], None]) -> None:
        """Register one synchronous callback for the exact terminal boundary."""

        if self._handler_exited or not callable(callback):
            raise CqrsPipelineStateError("handler exit callback is unavailable")
        self._handler_exit_callbacks.append(callback)

    def _notify_handler_exit(self) -> tuple[BaseException, ...]:
        if self._handler_exited:
            return ()
        self._handler_exited = True
        errors: list[BaseException] = []
        for callback in reversed(self._handler_exit_callbacks):
            try:
                callback()
            except BaseException as error:
                errors.append(error)
        return tuple(errors)


@runtime_checkable
class CqrsInvocationInterceptor(Protocol):
    """Wrap one CQRS handler invocation."""

    async def intercept(
        self,
        context: CqrsInvocationContext,
        next: CqrsNext,
    ) -> object: ...


class CqrsInterceptorPhase(StrEnum):
    """Stable execution regions for CQRS invocation interceptors."""

    OUTER = "outer"
    GRAPH = "graph"
    HANDLER = "handler"


type CqrsInterceptor = Token | CqrsInvocationInterceptor


@dataclass(frozen=True, slots=True)
class CqrsInterceptorBinding:
    """Pair one provider token or direct instance with an execution phase."""

    interceptor: CqrsInterceptor
    phase: CqrsInterceptorPhase
    handler_kinds: tuple[HandlerKind, ...] | None = None

    def __post_init__(self) -> None:
        try:
            phase = (
                self.phase
                if isinstance(self.phase, CqrsInterceptorPhase)
                else CqrsInterceptorPhase(self.phase)
            )
        except (TypeError, ValueError) as error:
            raise CqrsConfigurationError("invalid CQRS interceptor phase") from error
        object.__setattr__(self, "phase", phase)
        if isinstance(self.interceptor, str | type):
            try:
                token = validate_token(self.interceptor)
            except BootstrapError as error:
                raise CqrsConfigurationError(
                    "invalid CQRS interceptor token"
                ) from error
            object.__setattr__(self, "interceptor", token)
        elif not callable(getattr(self.interceptor, "intercept", None)):
            raise CqrsConfigurationError(
                "direct CQRS interceptor must expose intercept(context, next)"
            )
        if self.handler_kinds is not None:
            try:
                kinds = tuple(self.handler_kinds)
            except TypeError as error:
                raise CqrsConfigurationError(
                    "CQRS interceptor handler_kinds must be iterable"
                ) from error
            if not kinds or any(not isinstance(kind, HandlerKind) for kind in kinds):
                raise CqrsConfigurationError(
                    "CQRS interceptor handler_kinds must contain HandlerKind values"
                )
            object.__setattr__(self, "handler_kinds", tuple(dict.fromkeys(kinds)))


_CQRS_INTERCEPTORS_ATTRIBUTE = "__nestpy_cqrs_interceptors__"


def use_cqrs_interceptors[TargetT](
    *items: CqrsInterceptor | CqrsInterceptorBinding,
    phase: CqrsInterceptorPhase = CqrsInterceptorPhase.HANDLER,
) -> Callable[[TargetT], TargetT]:
    """Attach one ordered direct interceptor declaration to a handler class."""

    bindings = tuple(
        item
        if isinstance(item, CqrsInterceptorBinding)
        else CqrsInterceptorBinding(item, phase)
        for item in items
    )

    def decorate(target: TargetT) -> TargetT:
        if not isinstance(target, type) and not inspect.isfunction(target):
            raise CqrsConfigurationError("invalid CQRS interceptor target")
        existing = target.__dict__.get(_CQRS_INTERCEPTORS_ATTRIBUTE, ())
        if not isinstance(existing, tuple) or any(
            not isinstance(item, CqrsInterceptorBinding) for item in existing
        ):
            raise CqrsConfigurationError("CQRS interceptor metadata is invalid")
        setattr(target, _CQRS_INTERCEPTORS_ATTRIBUTE, (*bindings, *existing))
        return target

    return decorate


def _interceptor_metadata(target: object) -> tuple[CqrsInterceptorBinding, ...]:
    value = getattr(target, "__dict__", {}).get(_CQRS_INTERCEPTORS_ATTRIBUTE, ())
    return value if isinstance(value, tuple) else ()


def _module_label(module_id: ModuleId) -> str:
    label = module_id.module.__qualname__
    return label if module_id.key is None else f"{label}[{module_id.key}]"


__all__ = [
    "CqrsCompletionMapper",
    "CqrsInterceptorBinding",
    "CqrsInterceptorPhase",
    "CqrsInvocationCompletion",
    "CqrsInvocationContext",
    "CqrsInvocationInterceptor",
    "CqrsNext",
    "CqrsScopeCompletion",
    "use_cqrs_interceptors",
]
