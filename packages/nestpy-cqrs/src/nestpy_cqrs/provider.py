"""Nestpy-scoped CQRS handler provider."""

from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import cast

from cqrs_core import (
    DispatchContext,
    HandlerKind,
    HandlerRegistration,
    Message,
    RegisteredHandler,
    get_handler_metadata,
)
from nestpy import (
    ClassProvider,
    DiscoveryService,
    ModuleId,
    ModulesContainer,
    ProviderRef,
    ScopedResolver,
    Token,
    ValueProvider,
    WorkScopeFactory,
)

from nestpy_cqrs.bindings import CqrsHandlerBinding
from nestpy_cqrs.errors import CqrsConfigurationError


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
    token: Token
    module_id: ModuleId | None
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
    def __init__(self, scopes: WorkScopeFactory, entry: _BindingEntry) -> None:
        self._scopes = scopes
        self._entry = entry

    async def handle(self, message: Message) -> object:
        async def invoke(resolver: ScopedResolver) -> object:
            handler = await resolver.resolve(self._entry.token)
            method = getattr(handler, "handle", None)
            if not callable(method) or not inspect.iscoroutinefunction(method):
                raise CqrsConfigurationError(
                    "Nestpy CQRS handler must expose async handle(message)"
                )
            result = method(message)
            if not inspect.isawaitable(result):
                raise CqrsConfigurationError(
                    "Nestpy CQRS handler handle(message) must be async"
                )
            return await result

        if self._entry.module_id is None:
            return await self._scopes.run(invoke)
        return await self._scopes.run_in(self._entry.module_id, invoke)


class NestpyHandlerProvider:
    """Resolve every CQRS handler invocation in a fresh Nestpy work scope."""

    def __init__(self, scopes: WorkScopeFactory, plan: _BindingPlan) -> None:
        self._scopes = scopes
        self._plan = plan

    def provide(
        self,
        registration: HandlerRegistration,
        context: DispatchContext,
    ) -> AbstractAsyncContextManager[object]:
        del context
        entry = self._plan.entry_for(registration)

        @asynccontextmanager
        async def invocation() -> AsyncIterator[object]:
            yield _ScopedHandler(self._scopes, entry)

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
                alias=f"nestpy_cqrs:{key}:handler:{index}",
            )
        )
    return _ExplicitBindings(module_id, tuple(entries))


def _binding_plan(
    explicit: _ExplicitBindings,
    discovery: DiscoveryService,
    modules: ModulesContainer,
) -> _BindingPlan:
    entries: list[_BindingEntry] = []
    explicit_providers: set[ProviderRef] = set()
    seen_events: set[tuple[type[Message], ProviderRef]] = set()

    for configured in explicit.entries:
        provider = modules.provider(explicit.module_id, configured.alias)
        if provider is None:
            raise CqrsConfigurationError("explicit CQRS handler alias is unavailable")
        explicit_providers.add(provider.canonical)
        binding = configured.binding
        if binding.kind is HandlerKind.EVENT:
            identity = (binding.message_type, provider.canonical)
            if identity in seen_events:
                raise CqrsConfigurationError(
                    "duplicate event handler binding for one canonical provider"
                )
            seen_events.add(identity)
        entries.append(
            _BindingEntry(
                kind=binding.kind,
                message_type=binding.message_type,
                token=configured.alias,
                module_id=None,
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
        entries.append(
            _BindingEntry(
                kind=metadata.kind,
                message_type=metadata.message_type,
                token=provider.token,
                module_id=provider.ref.module_id,
                marker=_HandlerMarker(),
                identity_name=_provider_name(provider.ref),
                identity_id=id(provider.canonical),
            )
        )
    return _BindingPlan(tuple(entries))


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
