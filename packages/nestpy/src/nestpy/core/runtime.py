"""Async-first DI container, scopes, resources, and lifecycle for N2."""

from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, cast, runtime_checkable

from nestpy.core.compiler import (
    CompiledGraph,
    ModuleId,
    ProviderRef,
)
from nestpy.core.discovery import RuntimeDiscoveryService, RuntimeModulesContainer
from nestpy.core.errors import (
    ApplicationStateError,
    LifecycleError,
    ResourceError,
    ScopeClosedError,
    ScopeError,
)
from nestpy.core.options import ApplicationOptions
from nestpy.core.protocols import (
    DiscoveryService,
    ModulesContainer,
    ScopedResolver,
    ShutdownContext,
    WorkScopeFactory,
)
from nestpy.core.providers import (
    AliasProvider,
    ClassProvider,
    FactoryProvider,
    Scope,
    ValueProvider,
)
from nestpy.core.reflection import Reflector

logger = logging.getLogger(__name__)


class _LingeringQuiesceError(TimeoutError):
    """A quiesce hook ignored cancellation through its reserved grace."""


class ApplicationState(StrEnum):
    """Application lifecycle states owned by the N2 kernel."""

    COMPILED = "compiled"
    STARTING = "starting"
    STARTED = "started"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


class LeaseState(StrEnum):
    """Request scope lease states."""

    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class ScopeLease:
    """Invalidatable guard retained by request-scoped resolvers."""

    __slots__ = ("_state",)

    def __init__(self) -> None:
        self._state = LeaseState.OPEN

    @property
    def state(self) -> LeaseState:
        return self._state

    def check(self, *, allow_closing: bool = False) -> None:
        if self._state is LeaseState.OPEN:
            return
        if allow_closing and self._state is LeaseState.CLOSING:
            return
        raise ScopeClosedError("scope lease is not open")

    def begin_close(self) -> None:
        if self._state is LeaseState.OPEN:
            self._state = LeaseState.CLOSING

    def close(self) -> None:
        self._state = LeaseState.CLOSED


@dataclass(slots=True)
class _CleanupRecord:
    """One entered context manager and its async cleanup operation."""

    exit: Callable[[], Awaitable[None]]
    label: str


class _ResourceStack:
    """LIFO resource ownership with async and executor-backed sync exits."""

    def __init__(self, executor: ThreadPoolExecutor) -> None:
        self._executor = executor
        self._records: list[_CleanupRecord] = []
        self._sync_futures: set[Future[object]] = set()
        self._closed = False

    def mark(self) -> int:
        return len(self._records)

    @property
    def pending_count(self) -> int:
        return len(self._records)

    async def enter(self, value: object, *, label: str) -> object:
        if self._closed:
            raise ResourceError(
                "resource stack is closed",
                code="resource.acquire_error",
            )
        async_enter = getattr(value, "__aenter__", None)
        async_exit = getattr(value, "__aexit__", None)
        if callable(async_enter) and callable(async_exit):
            entered = await async_enter()

            async def exit_async() -> None:
                await async_exit(None, None, None)

            self._records.append(_CleanupRecord(exit_async, label))
            return entered

        sync_enter = getattr(value, "__enter__", None)
        sync_exit = getattr(value, "__exit__", None)
        if callable(sync_enter) and callable(sync_exit):
            entered = await self._run_sync(sync_enter)

            async def exit_sync() -> None:
                await self._run_sync(sync_exit, None, None, None)

            self._records.append(_CleanupRecord(exit_sync, label))
            return entered
        return value

    async def rollback_to(self, mark: int) -> BaseException | None:
        return await self._close_records(mark)

    async def close(self, deadline: float | None = None) -> BaseException | None:
        self._closed = True
        return await self._close_records(0, deadline=deadline)

    async def _close_records(
        self,
        mark: int,
        *,
        deadline: float | None = None,
    ) -> BaseException | None:
        first_error: BaseException | None = None
        while len(self._records) > mark:
            record = self._records.pop()
            task = asyncio.ensure_future(record.exit())
            if deadline is None:
                try:
                    await task
                except BaseException as error:
                    if first_error is None:
                        first_error = error
                    logger.exception(
                        "Resource cleanup failed",
                        extra={"resource": record.label},
                    )
                continue
            remaining = _remaining(deadline)
            if remaining is not None and remaining <= 0:
                task.add_done_callback(_observe_cleanup_task)
                logger.error(
                    "Resource cleanup exceeded shutdown deadline",
                    extra={
                        "code": "resource.lingering_resource",
                        "resource": record.label,
                    },
                )
                if self._sync_futures:
                    logger.error(
                        "Sync resource worker continued past shutdown deadline",
                        extra={"code": "resource.lingering_worker"},
                    )
                if first_error is None:
                    first_error = TimeoutError("resource cleanup deadline exceeded")
                continue
            try:
                done, _ = await asyncio.wait({task}, timeout=remaining)
                if not done:
                    task.add_done_callback(_observe_cleanup_task)
                    logger.error(
                        "Resource cleanup exceeded shutdown deadline",
                        extra={
                            "code": "resource.lingering_resource",
                            "resource": record.label,
                        },
                    )
                    if self._sync_futures:
                        logger.error(
                            "Sync resource worker continued past shutdown deadline",
                            extra={"code": "resource.lingering_worker"},
                        )
                    if first_error is None:
                        first_error = TimeoutError("resource cleanup deadline exceeded")
                    continue
                await task
            except BaseException as error:
                if first_error is None:
                    first_error = error
                logger.exception(
                    "Resource cleanup failed",
                    extra={"resource": record.label},
                )
        return first_error

    async def _run_sync(self, function: Callable[..., object], *args: object) -> object:
        future = self._executor.submit(functools.partial(function, *args))
        self._sync_futures.add(future)
        future.add_done_callback(self._observe_sync_future)
        return await asyncio.wrap_future(future)

    def _observe_sync_future(self, future: Future[object]) -> None:
        self._sync_futures.discard(future)
        if future.cancelled():
            return
        error = future.exception()
        if error is not None:
            logger.error(
                "Sync resource worker failed",
                extra={"code": "resource.lingering_worker"},
                exc_info=(type(error), error, error.__traceback__),
            )


@dataclass(slots=True)
class _ScopeState:
    kind: str
    lease: ScopeLease | None
    cache: dict[ProviderRef, object] = field(default_factory=dict)
    inflight: dict[ProviderRef, asyncio.Future[object]] = field(default_factory=dict)
    resources: _ResourceStack | None = None
    active_users: dict[asyncio.Task[object], int] = field(default_factory=dict)
    users_empty: asyncio.Event = field(default_factory=asyncio.Event)

    def __post_init__(self) -> None:
        self.users_empty.set()

    def enter_user(self) -> None:
        task = asyncio.current_task()
        if task is None:
            raise ScopeError("scope resolution requires an asyncio task")
        if self.lease is not None:
            self.lease.check()
        self.active_users[task] = self.active_users.get(task, 0) + 1
        self.users_empty.clear()

    def exit_user(self) -> None:
        task = asyncio.current_task()
        if task is None or task not in self.active_users:
            return
        count = self.active_users[task] - 1
        if count:
            self.active_users[task] = count
        else:
            self.active_users.pop(task, None)
        if not self.active_users:
            self.users_empty.set()

    def cancel_inflight(self) -> None:
        for future in tuple(self.inflight.values()):
            if not future.done():
                future.cancel()

    async def wait_users(self, *, exclude: asyncio.Task[object] | None = None) -> None:
        while True:
            users = {task for task in self.active_users if task is not exclude}
            if not users:
                return
            await asyncio.sleep(0)


class _Resolver:
    def __init__(
        self,
        container: Container,
        module_id: ModuleId,
        scope: _ScopeState,
    ) -> None:
        self._container = container
        self._module_id = module_id
        self._scope = scope

    async def resolve(self, token: object) -> object:
        if not isinstance(token, (str, type)):
            raise ScopeError("resolver token must be a class or string")
        self._scope.enter_user()
        try:
            return await self._container.resolve_token(
                self._module_id,
                token,
                scope=self._scope,
            )
        finally:
            self._scope.exit_user()


class Container:
    """Native async-first provider container for one compiled graph."""

    def __init__(
        self,
        graph: CompiledGraph,
        *,
        work_scope_factory: Callable[[ModuleId], WorkScopeFactory] | None = None,
        intrinsic_provider: Callable[[object], object] | None = None,
    ) -> None:
        self.graph = graph
        self._work_scope_factory = work_scope_factory
        self._intrinsic_provider = intrinsic_provider
        self._executor = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="nestpy-resource",
        )
        self._application = _ScopeState(
            "application",
            None,
            resources=_ResourceStack(self._executor),
        )
        self._closed = False

    def resolver(self, module_id: ModuleId) -> ScopedResolver:
        return _Resolver(self, module_id, self._application)

    def new_request_scope(self, kind: str = "request") -> _ScopeState:
        return _ScopeState(
            kind,
            ScopeLease(),
            resources=_ResourceStack(self._executor),
        )

    async def resolve_token(
        self,
        module_id: ModuleId,
        token: object,
        *,
        scope: _ScopeState,
    ) -> object:
        ref = self.graph.visibility.get((module_id, token))
        if ref is None:
            raise ScopeError(
                f"token is not visible from module {module_id.module.__qualname__}"
            )
        return await self.resolve_ref(ref, scope=scope)

    async def resolve_ref(self, ref: ProviderRef, *, scope: _ScopeState) -> object:
        if self._closed:
            raise ScopeClosedError("container is closed")
        if scope.lease is not None:
            scope.lease.check()
        plan = self.graph.providers[ref]
        canonical = plan.canonical
        canonical_plan = self.graph.providers[canonical]
        effective_scope = canonical_plan.scope
        if effective_scope is Scope.SINGLETON:
            owner = self._application
        elif effective_scope is Scope.REQUEST:
            if scope.kind not in {"request", "work"} or scope.lease is None:
                raise ScopeError("request-scoped provider requires a request scope")
            owner = scope
        else:
            owner = scope
        if effective_scope is Scope.TRANSIENT:
            return await self._construct(canonical, scope=scope, owner=owner)
        return await self._resolve_cached(canonical, scope=owner)

    async def _resolve_cached(
        self,
        ref: ProviderRef,
        *,
        scope: _ScopeState,
    ) -> object:
        if ref in scope.cache:
            return scope.cache[ref]
        pending = scope.inflight.get(ref)
        if pending is None:
            pending = asyncio.create_task(
                self._construct(ref, scope=scope, owner=scope)
            )
            scope.inflight[ref] = pending
        try:
            value = await asyncio.shield(pending)
        except BaseException:
            if pending.done() and scope.inflight.get(ref) is pending:
                scope.inflight.pop(ref, None)
            raise
        if scope.inflight.get(ref) is pending:
            scope.inflight.pop(ref, None)
            scope.cache[ref] = value
        return value

    async def _construct(
        self,
        ref: ProviderRef,
        *,
        scope: _ScopeState,
        owner: _ScopeState,
    ) -> object:
        plan = self.graph.providers[ref]
        declaration = plan.declaration
        if isinstance(declaration, AliasProvider):
            return await self.resolve_ref(plan.canonical, scope=scope)
        resources = owner.resources
        if resources is None:
            raise ResourceError("provider scope has no resource stack")
        mark = resources.mark()
        initial_cache = set(owner.cache)
        try:
            arguments: dict[str, object] = {}
            for dependency in plan.dependencies:
                if dependency.token is WorkScopeFactory:
                    if self._work_scope_factory is None:
                        raise ScopeError(
                            "WorkScopeFactory requires an application runtime"
                        )
                    arguments[dependency.parameter_name] = self._work_scope_factory(
                        ref.module_id
                    )
                elif dependency.token in {
                    ModulesContainer,
                    DiscoveryService,
                    Reflector,
                }:
                    if self._intrinsic_provider is None:
                        name = getattr(
                            dependency.token,
                            "__name__",
                            "framework dependency",
                        )
                        raise ScopeError(f"{name} requires an application runtime")
                    arguments[dependency.parameter_name] = self._intrinsic_provider(
                        dependency.token
                    )
                elif dependency.provider_ref is not None:
                    arguments[dependency.parameter_name] = await self.resolve_ref(
                        dependency.provider_ref,
                        scope=scope,
                    )
            if isinstance(declaration, ValueProvider):
                value = declaration.value
                manage = declaration.manage
            elif isinstance(declaration, ClassProvider):
                class_target = cast(type[object], declaration.use_class)
                value = class_target(**arguments)
                manage = declaration.manage
            elif isinstance(declaration, FactoryProvider):
                value = declaration.factory(**arguments)
                if inspect.isawaitable(value):
                    value = await value
                manage = declaration.manage
            else:
                raise ResourceError(
                    "unknown provider declaration",
                    code="resource.acquire_error",
                )
            if manage:
                value = await resources.enter(
                    value,
                    label=f"{ref.module_id.module.__qualname__}:{ref.token!r}",
                )
            return value
        except BaseException as error:
            secondary = await resources.rollback_to(mark)
            for cached_ref in set(owner.cache) - initial_cache:
                owner.cache.pop(cached_ref, None)
            if secondary is not None:
                logger.exception("Provider rollback failed", exc_info=secondary)
            raise error

    async def close(self, *, deadline: float | None = None) -> BaseException | None:
        if self._closed:
            return None
        self._closed = True
        self._application.cancel_inflight()
        inflight = tuple(self._application.inflight.values())
        if inflight:
            if deadline is None:
                await asyncio.gather(*inflight, return_exceptions=True)
                pending: set[asyncio.Future[object]] = set()
            else:
                _, pending = await asyncio.wait(
                    inflight,
                    timeout=_remaining(deadline),
                )
            if pending:
                for task in pending:
                    task.add_done_callback(_observe_bounded_task)
                logger.error(
                    "Application provider construction exceeded shutdown deadline",
                    extra={"code": "resource.lingering_resource"},
                )
                return TimeoutError("application provider construction did not stop")
            await asyncio.gather(*inflight, return_exceptions=True)
            self._application.inflight.clear()
        resources = self._application.resources
        if resources is None:
            return None
        error = await resources.close(deadline=deadline)
        self._executor.shutdown(wait=False, cancel_futures=False)
        return error


class RequestScope(AbstractAsyncContextManager[ScopedResolver]):
    """Request/work scope whose task owns its resource stack."""

    def __init__(
        self,
        container: Container,
        module_id: ModuleId,
        *,
        kind: str = "request",
        on_open: Callable[[RequestScope], None] | None = None,
        on_close: Callable[[RequestScope], None] | None = None,
    ) -> None:
        self._container = container
        self.module_id = module_id
        self.state = container.new_request_scope(kind)
        self.resolver: ScopedResolver = _Resolver(container, module_id, self.state)
        self._on_open = on_open
        self._on_close = on_close
        self._entered = False
        self._closed = False
        self._task: asyncio.Task[object] | None = None
        self._cleanup_task: asyncio.Task[BaseException | None] | None = None

    async def __aenter__(self) -> ScopedResolver:
        if self._entered:
            raise ScopeError("request scope cannot be entered twice")
        self._entered = True
        self._task = cast(asyncio.Task[object] | None, asyncio.current_task())
        if self._on_open is not None:
            self._on_open(self)
        return self.resolver

    def resolver_for(self, module_id: ModuleId) -> ScopedResolver:
        """Create a resolver for another module using this request lease."""

        if not self._entered or self._closed:
            raise ScopeError("request scope is not open")
        return _Resolver(self._container, module_id, self.state)

    async def resolve_ref(self, ref: ProviderRef) -> object:
        """Resolve a compiler-qualified provider reference in this lease."""

        if not self._entered or self._closed:
            raise ScopeError("request scope is not open")
        return await self._container.resolve_ref(ref, scope=self.state)

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        del exc_type, exc, tb
        if self._cleanup_task is None:
            if self.state.lease is not None:
                self.state.lease.begin_close()
            self._cleanup_task = asyncio.create_task(self._close())
        task = self._cleanup_task
        try:
            error = await asyncio.shield(task)
        except BaseException:
            task.add_done_callback(_observe_scope_cleanup)
            raise
        if error is not None:
            raise error

    async def _close(self) -> BaseException | None:
        try:
            await self.state.wait_users(exclude=self._task)
            self.state.cancel_inflight()
            pending = tuple(self.state.inflight.values())
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            resources = self.state.resources
            return None if resources is None else await resources.close()
        finally:
            if self.state.lease is not None:
                self.state.lease.close()
            self._closed = True
            if self._on_close is not None:
                self._on_close(self)


class _ModuleWorkScopeFactory:
    """Application-owned work-scope capability bound to one module."""

    def __init__(self, kernel: ApplicationKernel, module_id: ModuleId) -> None:
        self._kernel = kernel
        self._module_id = module_id

    @property
    def module_id(self) -> ModuleId:
        return self._module_id

    def open(self) -> RequestScope:
        return self._kernel._work_scope(self._module_id)

    async def run[T](
        self,
        operation: Callable[[ScopedResolver], Awaitable[T]],
    ) -> T:
        return await self._run(self._module_id, operation)

    async def run_in[T](
        self,
        module_id: ModuleId,
        operation: Callable[[ScopedResolver], Awaitable[T]],
    ) -> T:
        return await self._run(module_id, operation)

    async def _run[T](
        self,
        module_id: ModuleId,
        operation: Callable[[ScopedResolver], Awaitable[T]],
    ) -> T:
        async def execute() -> T:
            async with self._kernel._work_scope(module_id) as resolver:
                return await operation(resolver)

        task = asyncio.create_task(execute(), context=contextvars.Context())
        return await task


@dataclass(frozen=True, slots=True)
class _ShutdownContext:
    deadline: float | None

    def remaining(self) -> float | None:
        return _remaining(self.deadline)


@runtime_checkable
class DriverBinder(Protocol):
    """Driver hook used by the HTTP phase without importing a driver."""

    async def bind(self, kernel: ApplicationKernel) -> None:
        """Bind a compiled kernel to an external driver."""

    async def close(self) -> None:
        """Close a previously attempted binding."""


class NoopDriverBinder:
    """Binder used by N2 tests and non-HTTP applications."""

    async def bind(self, kernel: ApplicationKernel) -> None:
        del kernel

    async def close(self) -> None:
        return None


class ApplicationKernel:
    """Lifecycle orchestrator for one compiled, driver-neutral application."""

    def __init__(
        self,
        graph: CompiledGraph,
        *,
        options: ApplicationOptions | None = None,
        binder: DriverBinder | None = None,
    ) -> None:
        self.graph = graph
        self.options = options or ApplicationOptions()
        self._work_scope_factories: dict[ModuleId, WorkScopeFactory] = {}
        self._module_ids = frozenset(plan.module_id for plan in graph.modules)
        self.container = Container(
            graph,
            work_scope_factory=self._work_scope_factory,
            intrinsic_provider=self._intrinsic_provider,
        )
        self._reflector = Reflector()
        self._modules_container = RuntimeModulesContainer(
            graph,
            lambda ref: (
                ref in self.container._application.cache,
                self.container._application.cache.get(ref),
            ),
        )
        self._discovery_service = RuntimeDiscoveryService(
            self._modules_container,
            self._reflector,
        )
        self.binder = NoopDriverBinder() if binder is None else binder
        self.state = ApplicationState.COMPILED
        self._modules: list[object] = []
        self._module_initialized: list[object] = []
        self._bootstrapped: list[object] = []
        self._binding_attempted = False
        self._request_admission_open = False
        self._work_admission_open = False
        self._active_scopes: set[RequestScope] = set()
        self._active_event = asyncio.Event()
        self._active_event.set()
        self._lock = asyncio.Lock()
        self._shutdown_task: asyncio.Task[BaseException | None] | None = None

    def resolver(self, module_id: ModuleId) -> ScopedResolver:
        return self.container.resolver(module_id)

    def request_scope(self, module_id: ModuleId) -> RequestScope:
        scope = RequestScope(
            self.container,
            module_id,
            on_open=self._register_request_scope,
            on_close=self._unregister_scope,
        )
        return scope

    def _work_scope(self, module_id: ModuleId) -> RequestScope:
        if module_id not in self._module_ids:
            raise ScopeError("work scope requires a compiled module identity")
        return RequestScope(
            self.container,
            module_id,
            kind="work",
            on_open=self._register_work_scope,
            on_close=self._unregister_scope,
        )

    def _work_scope_factory(self, module_id: ModuleId) -> WorkScopeFactory:
        factory = self._work_scope_factories.get(module_id)
        if factory is None:
            factory = _ModuleWorkScopeFactory(self, module_id)
            self._work_scope_factories[module_id] = factory
        return factory

    def _intrinsic_provider(self, token: object) -> object:
        if token is ModulesContainer:
            return self._modules_container
        if token is DiscoveryService:
            return self._discovery_service
        if token is Reflector:
            return self._reflector
        raise ScopeError("unknown framework dependency")

    async def start(self) -> None:
        async with self._lock:
            if self.state is not ApplicationState.COMPILED:
                raise ApplicationStateError(
                    f"cannot start application in {self.state.value} state"
                )
            self.state = ApplicationState.STARTING
        try:
            self._modules = [plan.module() for plan in self.graph.modules]
            for ref in self.graph.provider_order:
                plan = self.graph.providers[ref]
                if plan.scope is Scope.SINGLETON:
                    await self.container.resolve_ref(
                        ref, scope=self.container._application
                    )
            for participant in self._modules:
                await _call_hook(participant, "on_module_init")
                self._module_initialized.append(participant)
            for ref in self.graph.provider_order:
                if self.graph.providers[ref].scope is Scope.SINGLETON:
                    participant = self.container._application.cache.get(ref)
                    if participant is not None:
                        await _call_hook(participant, "on_module_init")
                        self._module_initialized.append(participant)
            self._binding_attempted = True
            await self.binder.bind(self)
            self._work_admission_open = True
            for participant in self._module_initialized:
                await _call_hook(participant, "on_application_bootstrap")
                self._bootstrapped.append(participant)
            self._request_admission_open = True
            self.state = ApplicationState.STARTED
        except BaseException as error:
            await self._rollback(error)
            raise

    async def shutdown(self) -> None:
        async with self._lock:
            if self.state is ApplicationState.STOPPED:
                return
            if self.state is ApplicationState.STOPPING:
                cleanup_task = self._shutdown_task
                if cleanup_task is None:
                    raise ApplicationStateError(
                        "application shutdown task is unavailable"
                    )
            elif self.state is ApplicationState.STARTED:
                self.state = ApplicationState.STOPPING
                self._request_admission_open = False
                deadline = _deadline(self.options.shutdown_timeout)
                cleanup_task = asyncio.create_task(self._run_shutdown(deadline))
                self._shutdown_task = cleanup_task
            else:
                raise ApplicationStateError(
                    f"cannot shut down application in {self.state.value} state"
                )
        first_error = await asyncio.shield(cleanup_task)
        if first_error is not None:
            raise first_error

    async def _run_shutdown(self, deadline: float | None) -> BaseException | None:
        try:
            return await self._shutdown_steps(deadline)
        finally:
            self.state = ApplicationState.STOPPED

    async def _shutdown_steps(self, deadline: float | None) -> BaseException | None:
        first_error: BaseException | None = None
        cutoff = self._scope_drain_cutoff(deadline)
        cancellation_deadline = self._quiesce_cancellation_deadline(deadline)
        quiesce_lingering = False
        try:
            quiesce_error, quiesce_lingering = await self._run_reverse_quiesce(
                self._bootstrapped,
                cutoff,
                cancellation_deadline=cancellation_deadline,
            )
            if quiesce_error is not None:
                first_error = quiesce_error
        except BaseException as error:
            first_error = error
        finally:
            self._work_admission_open = False
        try:
            await self._drain_scopes(deadline, cutoff=cutoff)
        except BaseException as error:
            if first_error is None:
                first_error = error
        if quiesce_lingering:
            logger.error(
                "Shutdown teardown skipped after cancellation-resistant quiescence",
                extra={"code": "lifecycle.lingering_task"},
            )
            return first_error
        hook_error = await self._run_reverse_hooks(
            self._bootstrapped,
            "on_application_shutdown",
            deadline=deadline,
        )
        if first_error is None and hook_error is not None:
            first_error = hook_error
        if self._binding_attempted:
            try:
                await _await_bounded(self.binder.close(), deadline, "binder.close")
            except BaseException as error:
                if first_error is None:
                    first_error = error
        hook_error = await self._run_reverse_hooks(
            self._module_initialized,
            "on_module_destroy",
            deadline=deadline,
        )
        if first_error is None and hook_error is not None:
            first_error = hook_error
        try:
            resource_error = await self.container.close(deadline=deadline)
        except BaseException as error:
            resource_error = error
        if first_error is None and resource_error is not None:
            first_error = resource_error
        return first_error

    def _register_request_scope(self, scope: RequestScope) -> None:
        if not self._request_admission_open:
            raise ApplicationStateError("application is not accepting request scopes")
        self._track_scope(scope)

    def _register_work_scope(self, scope: RequestScope) -> None:
        if not self._work_admission_open:
            raise ApplicationStateError("application is not accepting work scopes")
        self._track_scope(scope)

    def _track_scope(self, scope: RequestScope) -> None:
        self._active_scopes.add(scope)
        self._active_event.clear()

    def _unregister_scope(self, scope: RequestScope) -> None:
        self._active_scopes.discard(scope)
        if not self._active_scopes:
            self._active_event.set()

    def _scope_drain_cutoff(self, deadline: float | None) -> float | None:
        if deadline is None:
            return None
        reserve = self.options.cancellation_grace + self.options.cleanup_reserve
        return max(asyncio.get_running_loop().time(), deadline - reserve)

    def _quiesce_cancellation_deadline(
        self,
        deadline: float | None,
    ) -> float | None:
        if deadline is None:
            return None
        return max(
            asyncio.get_running_loop().time(),
            deadline - self.options.cleanup_reserve,
        )

    async def _drain_scopes(
        self,
        deadline: float | None,
        *,
        cutoff: float | None = None,
    ) -> None:
        cutoff = self._scope_drain_cutoff(deadline) if cutoff is None else cutoff
        remaining = _remaining(cutoff)
        if self._active_scopes:
            try:
                if remaining is None:
                    await self._active_event.wait()
                else:
                    await asyncio.wait_for(self._active_event.wait(), remaining)
            except TimeoutError:
                for scope in tuple(self._active_scopes):
                    if scope.state.lease is not None:
                        scope.state.lease.begin_close()
        if self._active_scopes:
            current_task = asyncio.current_task()
            tasks: set[asyncio.Task[object]] = set()
            for scope in self._active_scopes:
                owner_task = _scope_task(scope)
                if owner_task is not None:
                    tasks.add(owner_task)
                tasks.update(scope.state.active_users)
            tasks.discard(cast(asyncio.Task[object] | None, current_task))
            for task in tasks:
                if not task.done():
                    task.cancel()
            grace = min(
                self.options.cancellation_grace,
                _remaining(deadline) or 0,
            )
            if tasks and grace > 0:
                _, pending = await asyncio.wait(tasks, timeout=grace)
            else:
                pending = {task for task in tasks if not task.done()}
            for _task in pending:
                logger.error(
                    "Request task remained active after shutdown grace",
                    extra={"code": "lifecycle.lingering_task"},
                )
            for scope in tuple(self._active_scopes):
                resources = scope.state.resources
                if resources is not None and (
                    resources.pending_count or scope.state.inflight
                ):
                    logger.error(
                        "Request scope resources remained open after shutdown grace",
                        extra={"code": "resource.lingering_resource"},
                    )

    async def _rollback(self, primary: BaseException) -> None:
        deadline = _deadline(self.options.shutdown_timeout)
        self._request_admission_open = False
        quiesce_error, quiesce_lingering = await self._run_reverse_quiesce(
            self._bootstrapped,
            self._scope_drain_cutoff(deadline),
            cancellation_deadline=self._quiesce_cancellation_deadline(deadline),
        )
        self._work_admission_open = False
        if quiesce_error is not None:
            logger.error(
                "Application quiescence rollback failed",
                exc_info=(
                    type(quiesce_error),
                    quiesce_error,
                    quiesce_error.__traceback__,
                ),
            )
        try:
            await self._drain_scopes(deadline)
        except BaseException:
            logger.exception("Application scope drain failed during rollback")
        if quiesce_lingering:
            logger.error(
                "Rollback teardown skipped after cancellation-resistant quiescence",
                extra={"code": "lifecycle.lingering_task"},
            )
            self.state = ApplicationState.FAILED
            return
        hook_error = await self._run_reverse_hooks(
            self._bootstrapped,
            "on_application_shutdown",
            deadline=deadline,
        )
        if hook_error is not None:
            logger.error(
                "Application shutdown rollback hook failed",
                exc_info=(type(hook_error), hook_error, hook_error.__traceback__),
            )
        if self._binding_attempted:
            try:
                await _await_bounded(
                    self.binder.close(),
                    deadline,
                    "binder.close",
                )
            except BaseException:
                logger.exception("Driver binder close failed during rollback")
        hook_error = await self._run_reverse_hooks(
            self._module_initialized,
            "on_module_destroy",
            deadline=deadline,
        )
        if hook_error is not None:
            logger.error(
                "Module destroy rollback hook failed",
                exc_info=(type(hook_error), hook_error, hook_error.__traceback__),
            )
        resource_error = await self.container.close(deadline=deadline)
        if resource_error is not None:
            logger.exception(
                "Application resource rollback failed", exc_info=resource_error
            )
        self._request_admission_open = False
        self._work_admission_open = False
        self.state = ApplicationState.FAILED
        del primary

    async def _run_reverse_quiesce(
        self,
        participants: list[object],
        deadline: float | None,
        *,
        cancellation_deadline: float | None,
    ) -> tuple[BaseException | None, bool]:
        first_error: BaseException | None = None
        lingering = False
        context = _ShutdownContext(deadline)
        for participant in reversed(participants):
            try:
                await _call_quiesce(
                    participant,
                    context,
                    deadline=deadline,
                    cancellation_deadline=cancellation_deadline,
                )
            except BaseException as error:
                if first_error is None:
                    first_error = error
                if isinstance(error, _LingeringQuiesceError):
                    lingering = True
                logger.exception(
                    "Lifecycle hook failed",
                    extra={"hook": "on_application_quiesce"},
                )
        return first_error, lingering

    async def _run_reverse_hooks(
        self,
        participants: list[object],
        hook_name: str,
        *,
        deadline: float | None = None,
    ) -> BaseException | None:
        first_error: BaseException | None = None
        for participant in reversed(participants):
            try:
                await _call_hook(participant, hook_name, deadline=deadline)
            except BaseException as error:
                if first_error is None:
                    first_error = error
                logger.exception("Lifecycle hook failed", extra={"hook": hook_name})
        return first_error


async def _call_hook(
    participant: object,
    name: str,
    *,
    deadline: float | None = None,
) -> None:
    hook = getattr(participant, name, None)
    if hook is None:
        return
    if not callable(hook) or not inspect.iscoroutinefunction(hook):
        raise LifecycleError(
            f"lifecycle hook {name} must be async",
            code="lifecycle.startup_error",
        )
    try:
        parameters = inspect.signature(hook).parameters
    except (TypeError, ValueError) as error:
        raise LifecycleError(
            f"cannot inspect lifecycle hook {name}",
            code="lifecycle.startup_error",
        ) from error
    if parameters:
        raise LifecycleError(
            f"lifecycle hook {name} must accept only self",
            code="lifecycle.startup_error",
        )
    await _await_bounded(hook(), deadline, f"lifecycle.{name}")


async def _call_quiesce(
    participant: object,
    context: ShutdownContext,
    *,
    deadline: float | None,
    cancellation_deadline: float | None,
) -> None:
    hook = getattr(participant, "on_application_quiesce", None)
    if hook is None:
        return
    if not callable(hook) or not inspect.iscoroutinefunction(hook):
        raise LifecycleError(
            "lifecycle hook on_application_quiesce must be async",
            code="lifecycle.startup_error",
        )
    try:
        parameters = inspect.signature(hook).parameters
    except (TypeError, ValueError) as error:
        raise LifecycleError(
            "cannot inspect lifecycle hook on_application_quiesce",
            code="lifecycle.startup_error",
        ) from error
    if len(parameters) != 1:
        raise LifecycleError(
            "lifecycle hook on_application_quiesce must accept one context",
            code="lifecycle.startup_error",
        )
    remaining = _remaining(deadline)
    if remaining is not None and remaining <= 0:
        raise TimeoutError(
            "lifecycle.on_application_quiesce exceeded shutdown deadline"
        )
    await _await_bounded(
        hook(context),
        deadline,
        "lifecycle.on_application_quiesce",
        cancel_on_timeout=True,
        cancellation_deadline=cancellation_deadline,
    )


async def _await_bounded(
    awaitable: Awaitable[object],
    deadline: float | None,
    label: str,
    *,
    cancel_on_timeout: bool = False,
    cancellation_deadline: float | None = None,
) -> object:
    future = asyncio.ensure_future(awaitable)
    if deadline is None:
        return await future
    remaining = _remaining(deadline)
    if remaining is not None and remaining <= 0:
        if cancel_on_timeout:
            future.cancel()
            await _wait_for_cancellation(
                future,
                cancellation_deadline,
                label,
            )
        else:
            future.add_done_callback(_observe_bounded_task)
        raise TimeoutError(f"{label} exceeded shutdown deadline")
    try:
        done, _ = await asyncio.wait({future}, timeout=remaining)
    except asyncio.CancelledError:
        future.add_done_callback(_observe_bounded_task)
        raise
    if not done:
        if cancel_on_timeout:
            future.cancel()
            await _wait_for_cancellation(
                future,
                cancellation_deadline,
                label,
            )
        else:
            future.add_done_callback(_observe_bounded_task)
        logger.error(
            "Shutdown operation exceeded deadline",
            extra={"code": "lifecycle.lingering_task", "operation": label},
        )
        raise TimeoutError(f"{label} exceeded shutdown deadline")
    return future.result()


async def _wait_for_cancellation(
    future: asyncio.Future[object],
    deadline: float | None,
    label: str,
) -> None:
    if deadline is None:
        await asyncio.gather(future, return_exceptions=True)
        return
    done, _ = await asyncio.wait({future}, timeout=_remaining(deadline))
    if done:
        await asyncio.gather(future, return_exceptions=True)
        return
    future.add_done_callback(_observe_bounded_task)
    raise _LingeringQuiesceError(f"{label} ignored cancellation")


def _observe_bounded_task(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    error = future.exception()
    if error is not None:
        logger.error(
            "Lingering shutdown operation failed",
            extra={"code": "lifecycle.lingering_task"},
            exc_info=(type(error), error, error.__traceback__),
        )


def _observe_cleanup_task(task: asyncio.Future[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "Lingering resource cleanup failed",
            extra={"code": "resource.lingering_resource"},
            exc_info=(type(error), error, error.__traceback__),
        )


def _observe_scope_cleanup(
    task: asyncio.Future[BaseException | None],
) -> None:
    if task.cancelled():
        return
    try:
        error = task.result()
    except BaseException as task_error:
        logger.error(
            "Request scope cleanup task failed",
            extra={"code": "resource.lingering_resource"},
            exc_info=(type(task_error), task_error, task_error.__traceback__),
        )
        return
    if error is not None:
        logger.error(
            "Request scope resource cleanup failed",
            extra={"code": "resource.cleanup_error"},
            exc_info=(type(error), error, error.__traceback__),
        )


def _scope_task(scope: RequestScope) -> asyncio.Task[object] | None:
    task = getattr(scope, "_task", None)
    if isinstance(task, asyncio.Task):
        return task
    return None


def _deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    return asyncio.get_running_loop().time() + timeout


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - asyncio.get_running_loop().time())


__all__ = [
    "ApplicationKernel",
    "ApplicationState",
    "Container",
    "DriverBinder",
    "LeaseState",
    "NoopDriverBinder",
    "RequestScope",
    "ScopeLease",
]
