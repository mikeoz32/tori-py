"""ToriPy-scoped CQRS handler provider."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast

from tori_py import (
    ClassProvider,
    DiscoveryService,
    ModuleId,
    ModulesContainer,
    ProviderRef,
    ProviderView,
    ScopeCancellationError,
    ScopedResolver,
    ScopeFinalizationError,
    Token,
    ValueProvider,
    WorkScopeFactory,
)
from tori_py_cqrs_core import (
    DispatchContext,
    HandlerKind,
    HandlerRegistration,
    Message,
    RegisteredHandler,
    get_handler_metadata,
)

from tori_py_cqrs.bindings import CqrsHandlerBinding
from tori_py_cqrs.errors import (
    CqrsConfigurationError,
    CqrsHandlerExitCancellationError,
    CqrsHandlerExitError,
    CqrsPipelineStateError,
)
from tori_py_cqrs.invocation import (
    CqrsInterceptorBinding,
    CqrsInterceptorPhase,
    CqrsInvocationCompletion,
    CqrsInvocationContext,
    CqrsScopeCompletion,
    _interceptor_metadata,
)
from tori_py_cqrs.options import CqrsModuleOptions


class _HandlerMarker:
    def __call__(self) -> None:
        raise CqrsConfigurationError("handler marker cannot be invoked directly")


@dataclass(frozen=True, slots=True)
class _ExplicitBindingEntry:
    binding: CqrsHandlerBinding
    alias: Token


@dataclass(frozen=True, slots=True)
class _ExplicitBindings:
    module_id: ModuleId
    entries: tuple[_ExplicitBindingEntry, ...]


@dataclass(frozen=True, slots=True)
class _BindingEntry:
    kind: HandlerKind
    message_type: type[Message]
    handler_ref: ProviderRef
    owner_module: ModuleId
    interceptors: tuple[CqrsInterceptorBinding, ...]
    marker: _HandlerMarker
    identity_name: str
    identity_id: int


class _BindingPlan:
    __slots__ = ("_by_marker", "entries")

    def __init__(self, entries: tuple[_BindingEntry, ...]) -> None:
        self.entries = entries
        self._by_marker = {id(entry.marker): entry for entry in entries}

    def entry_for(self, registration: HandlerRegistration) -> _BindingEntry:
        registered = cast(RegisteredHandler, registration)
        entry = self._by_marker.get(id(registered.target))
        if entry is None or registered.target is not entry.marker:
            raise CqrsConfigurationError("unknown CQRS handler registration")
        return entry

    def failure_identity(self, marker_id: int) -> tuple[str, int]:
        entry = self._by_marker.get(marker_id)
        if entry is None:
            raise CqrsConfigurationError("unknown CQRS event handler failure")
        return entry.identity_name, entry.identity_id


class _ScopedHandler:
    def __init__(
        self,
        scopes: WorkScopeFactory,
        entry: _BindingEntry,
        dispatch_context: DispatchContext,
    ) -> None:
        self._scopes = scopes
        self._entry = entry
        self._dispatch_context = dispatch_context

    async def handle(self, message: Message) -> object:
        completion = CqrsInvocationCompletion()
        result: object | None = None
        result_available = False
        body_error: BaseException | None = None
        handler_exit_errors: tuple[BaseException, ...] = ()

        async def invoke(resolver: ScopedResolver) -> object:
            nonlocal body_error, handler_exit_errors, result, result_available
            context = CqrsInvocationContext(
                application_id=self._scopes.application_id,
                dispatch_context=self._dispatch_context,
                handler_kind=self._entry.kind,
                handler_ref=self._entry.handler_ref,
                owner_module=self._entry.owner_module,
                resolver=resolver,
                completion=completion,
                metadata=_invocation_metadata(self._entry, self._dispatch_context),
            )

            async def terminal() -> object:
                nonlocal handler_exit_errors
                try:
                    handler = await resolver.resolve(self._entry.handler_ref.token)
                    method = getattr(handler, "handle", None)
                    if not callable(method) or not inspect.iscoroutinefunction(method):
                        raise CqrsConfigurationError(
                            "ToriPy CQRS handler must expose async handle(message)"
                        )
                    handled = method(message)
                    if not inspect.isawaitable(handled):
                        raise CqrsConfigurationError(
                            "ToriPy CQRS handler handle(message) must be async"
                        )
                    return await handled
                finally:
                    handler_exit_errors = context._notify_handler_exit()

            async def dispatch(index: int) -> object:
                if index == len(self._entry.interceptors):
                    return await terminal()
                configured = self._entry.interceptors[index].interceptor
                interceptor = (
                    await resolver.resolve(configured)
                    if isinstance(configured, str | type)
                    else configured
                )
                method = getattr(interceptor, "intercept", None)
                if not callable(method) or not inspect.iscoroutinefunction(method):
                    raise CqrsConfigurationError(
                        "ToriPy CQRS interceptor must expose async "
                        "intercept(context, next)"
                    )
                called = False

                async def next_once() -> object:
                    nonlocal called
                    if called:
                        raise CqrsPipelineStateError(
                            "CQRS pipeline next callback was called twice"
                        )
                    called = True
                    return await dispatch(index + 1)

                intercepted = method(context, next_once)
                if not inspect.isawaitable(intercepted):
                    raise CqrsConfigurationError(
                        "ToriPy CQRS interceptor intercept(context, next) must be async"
                    )
                return await intercepted

            try:
                result = await dispatch(0)
                result_available = True
                return result
            except BaseException as error:
                body_error = error
                raise
            finally:
                completion._freeze()

        try:
            scoped_result = await self._scopes.run_in(self._entry.owner_module, invoke)
        except BaseException as error:
            completion._freeze()
            scope_error = (
                error
                if isinstance(error, ScopeFinalizationError | ScopeCancellationError)
                else None
            )
            completed_body_error = (
                scope_error.body_error
                if body_error is None and scope_error is not None
                else body_error
            )
            current = _handler_exit_error(error, handler_exit_errors)
            mapped = completion._apply(
                CqrsScopeCompletion(
                    result=result,
                    result_available=result_available,
                    body_error=completed_body_error,
                    scope_error=scope_error,
                ),
                current,
            )
            if mapped is error:
                raise
            assert mapped is not None
            raise mapped from (mapped.__cause__ or current)
        completion._freeze()
        current = _handler_exit_error(None, handler_exit_errors)
        mapped = completion._apply(
            CqrsScopeCompletion(
                result=result,
                result_available=result_available,
                body_error=body_error,
                scope_error=None,
            ),
            current,
        )
        if mapped is not None:
            raise mapped
        return scoped_result


class ToriPyHandlerProvider:
    """Resolve every CQRS handler invocation in a fresh ToriPy work scope."""

    def __init__(self, scopes: WorkScopeFactory, plan: _BindingPlan) -> None:
        self._scopes = scopes
        self._plan = plan

    def provide(
        self,
        registration: HandlerRegistration,
        context: DispatchContext,
    ) -> AbstractAsyncContextManager[object]:
        entry = self._plan.entry_for(registration)

        @asynccontextmanager
        async def invocation() -> AsyncIterator[object]:
            yield _ScopedHandler(self._scopes, entry, context)

        return invocation()


def _explicit_bindings(
    module_id: ModuleId,
    key: str,
    bindings: tuple[CqrsHandlerBinding, ...],
) -> _ExplicitBindings:
    seen_events: set[tuple[type[Message], Token]] = set()
    entries: list[_ExplicitBindingEntry] = []
    for index, binding in enumerate(bindings):
        if binding.kind is HandlerKind.EVENT:
            identity = (binding.message_type, binding.token)
            if identity in seen_events:
                raise CqrsConfigurationError(
                    "duplicate event handler binding for one provider token"
                )
            seen_events.add(identity)
        entries.append(
            _ExplicitBindingEntry(
                binding=binding,
                alias=f"tori_py_cqrs:{key}:handler:{index}",
            )
        )
    return _ExplicitBindings(module_id, tuple(entries))


def _binding_plan(
    explicit: _ExplicitBindings,
    discovery: DiscoveryService,
    modules: ModulesContainer,
    options: CqrsModuleOptions,
) -> _BindingPlan:
    entries: list[_BindingEntry] = []
    explicit_providers: set[ProviderRef] = set()
    seen_events: set[tuple[type[Message], ProviderRef]] = set()

    for configured in explicit.entries:
        provider = modules.provider(explicit.module_id, configured.alias)
        if provider is None:
            raise CqrsConfigurationError("explicit CQRS handler alias is unavailable")
        explicit_providers.add(provider.canonical)
        canonical = modules.provider(
            provider.canonical.module_id,
            provider.canonical.token,
        )
        if canonical is None:
            raise CqrsConfigurationError("canonical CQRS handler is unavailable")
        binding = configured.binding
        if binding.kind is HandlerKind.EVENT:
            identity = (binding.message_type, provider.canonical)
            if identity in seen_events:
                raise CqrsConfigurationError(
                    "duplicate event handler binding for one canonical provider"
                )
            seen_events.add(identity)
        interceptors = _ordered_interceptors(
            binding.kind,
            binding.interceptors,
            _static_interceptors(canonical),
            options,
        )
        _validate_interceptor_visibility(
            provider.canonical.module_id,
            interceptors,
            modules,
        )
        entries.append(
            _BindingEntry(
                kind=binding.kind,
                message_type=binding.message_type,
                handler_ref=provider.canonical,
                owner_module=provider.canonical.module_id,
                interceptors=interceptors,
                marker=_HandlerMarker(),
                identity_name=_token_name(binding.token),
                identity_id=id(binding.token),
            )
        )

    for provider in discovery.get_providers():
        if provider.canonical in explicit_providers or not isinstance(
            provider.declaration, ClassProvider | ValueProvider
        ):
            continue
        target = provider.implementation
        if target is None:
            continue
        metadata = get_handler_metadata(target)
        if metadata is None:
            continue
        if metadata.kind is HandlerKind.EVENT:
            identity = (metadata.message_type, provider.canonical)
            if identity in seen_events:
                continue
            seen_events.add(identity)
        interceptors = _ordered_interceptors(
            metadata.kind,
            (),
            _interceptor_metadata(target),
            options,
        )
        _validate_interceptor_visibility(
            provider.canonical.module_id,
            interceptors,
            modules,
        )
        entries.append(
            _BindingEntry(
                kind=metadata.kind,
                message_type=metadata.message_type,
                handler_ref=provider.canonical,
                owner_module=provider.canonical.module_id,
                interceptors=interceptors,
                marker=_HandlerMarker(),
                identity_name=_provider_name(provider.ref),
                identity_id=id(provider.canonical),
            )
        )
    return _BindingPlan(tuple(entries))


def _static_interceptors(
    provider: ProviderView,
) -> tuple[CqrsInterceptorBinding, ...]:
    if not isinstance(provider.declaration, ClassProvider | ValueProvider):
        return ()
    implementation = provider.implementation
    if implementation is None:
        return ()
    return _interceptor_metadata(implementation)


def _ordered_interceptors(
    kind: HandlerKind,
    explicit: tuple[CqrsInterceptorBinding, ...],
    decorated: tuple[CqrsInterceptorBinding, ...],
    options: CqrsModuleOptions,
) -> tuple[CqrsInterceptorBinding, ...]:
    declared = (*explicit, *decorated)
    graph = cast(
        tuple[CqrsInterceptorBinding, ...],
        {
            HandlerKind.COMMAND: options.command_interceptors,
            HandlerKind.QUERY: options.query_interceptors,
            HandlerKind.EVENT: options.event_interceptors,
        }[kind],
    )
    for interceptor in (*declared, *graph):
        if (
            interceptor.handler_kinds is not None
            and kind not in interceptor.handler_kinds
        ):
            raise CqrsConfigurationError(
                f"{kind.value} handler uses an incompatible CQRS interceptor"
            )
    return (
        *(item for item in declared if item.phase is CqrsInterceptorPhase.OUTER),
        *graph,
        *(item for item in declared if item.phase is CqrsInterceptorPhase.GRAPH),
        *(item for item in declared if item.phase is CqrsInterceptorPhase.HANDLER),
    )


def _validate_interceptor_visibility(
    owner_module: ModuleId,
    interceptors: tuple[CqrsInterceptorBinding, ...],
    modules: ModulesContainer,
) -> None:
    for binding in interceptors:
        interceptor = binding.interceptor
        if (
            isinstance(interceptor, str | type)
            and modules.provider(
                owner_module,
                interceptor,
            )
            is None
        ):
            raise CqrsConfigurationError(
                f"CQRS interceptor {interceptor!r} is not visible from handler module"
            )


def _invocation_metadata(
    entry: _BindingEntry,
    context: DispatchContext,
) -> dict[str, object]:
    envelope = context.envelope
    return {
        "handler": _provider_name(entry.handler_ref),
        "handler_kind": entry.kind.value,
        "message_type": envelope.message_type,
        "message_id": str(envelope.message_id),
        "correlation_id": (
            None if envelope.correlation_id is None else str(envelope.correlation_id)
        ),
    }


def _handler_exit_error(
    body_error: BaseException | None,
    callback_errors: tuple[BaseException, ...],
) -> BaseException | None:
    if not callback_errors:
        return body_error
    if isinstance(body_error, (KeyboardInterrupt, SystemExit)):
        for error in callback_errors:
            body_error.add_note(
                f"CQRS handler exit callback failed: {type(error).__name__}: {error}"
            )
        return body_error
    control = next(
        (
            error
            for error in callback_errors
            if isinstance(error, (KeyboardInterrupt, SystemExit))
        ),
        None,
    )
    if isinstance(control, (KeyboardInterrupt, SystemExit)):
        secondary = (
            *((body_error,) if body_error is not None else ()),
            *(error for error in callback_errors if error is not control),
        )
        for error in secondary:
            control.add_note(
                "CQRS handler finalization also failed: "
                f"{type(error).__name__}: {error}"
            )
        return control
    cancellation = (
        body_error
        if isinstance(body_error, asyncio.CancelledError)
        else next(
            (
                error
                for error in callback_errors
                if isinstance(error, asyncio.CancelledError)
            ),
            None,
        )
    )
    if isinstance(cancellation, asyncio.CancelledError):
        body_secondary = (
            (body_error,)
            if body_error is not None and body_error is not cancellation
            else ()
        )
        secondary = (
            *body_secondary,
            *(error for error in callback_errors if error is not cancellation),
        )
        return CqrsHandlerExitCancellationError(cancellation, secondary)
    return CqrsHandlerExitError(body_error, callback_errors)


def _token_name(token: Token) -> str:
    if isinstance(token, str):
        return token
    return f"{token.__module__}.{token.__qualname__}"


def _provider_name(ref: ProviderRef) -> str:
    module_id = ref.module_id
    module_name = f"{module_id.module.__module__}.{module_id.module.__qualname__}"
    if module_id.key is not None:
        module_name = f"{module_name}[{module_id.key}]"
    return f"{module_name}:{_token_name(ref.token)}"


__all__: list[str] = []
