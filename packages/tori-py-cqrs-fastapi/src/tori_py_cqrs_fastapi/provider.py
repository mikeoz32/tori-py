"""Explicit FastAPI adapter handler provider."""

import asyncio
import inspect
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from typing import cast, get_type_hints

from tori_py_cqrs_core.protocols import DispatchContext, HandlerRegistration
from tori_py_cqrs_core.registrations import RegisteredHandler, TargetMode

logger = logging.getLogger(__name__)


class FastAPIHandlerProvider:
    """Resolve handlers without using FastAPI's private dependency solver.

    Handler classes and factories are request/dispatch scoped by default. App
    resources can be registered explicitly and are closed when the adapter
    lifespan ends.
    """

    def __init__(self, dependencies: Mapping[object, object] | None = None) -> None:
        self._app: object | None = None
        self._dependencies = dict(dependencies or {})
        self._app_resources: dict[int, tuple[object, object]] = {}
        self._active_scopes: set[object] = set()
        self._scopes_empty = asyncio.Event()
        self._scopes_empty.set()
        self._closing = False
        self._closed = False

    @property
    def app(self) -> object | None:
        """Return the application bound by the adapter lifespan."""

        return self._app

    def bind_app(self, app: object) -> None:
        """Bind this provider to one application instance."""

        if self._closed:
            raise RuntimeError("handler provider is closed")
        if self._closing:
            raise RuntimeError("handler provider is closing")
        if self._app is not None and self._app is not app:
            raise RuntimeError("handler provider is already bound to another app")
        self._app = app

    def register_app_resource(self, key: object, resource: object) -> None:
        """Register an app-scoped resource and its eventual cleanup owner."""

        if self._closed:
            raise RuntimeError("handler provider is closed")
        if self._closing:
            raise RuntimeError("handler provider is closing")
        if id(key) in self._app_resources:
            raise RuntimeError("app resource key is already registered")
        self._app_resources[id(key)] = (key, resource)

    def provide(
        self,
        registration: HandlerRegistration,
        context: DispatchContext,
    ):
        """Create one explicit handler scope."""

        del context
        registered = cast(RegisteredHandler, registration)

        @asynccontextmanager
        async def scope() -> AsyncIterator[object]:
            if self._closing or self._closed:
                raise RuntimeError("handler provider is closing")
            scope_token = object()
            self._active_scopes.add(scope_token)
            self._scopes_empty.clear()
            try:
                handler, owned = await self._resolve(registered)
                yield handler
            finally:
                try:
                    if "owned" in locals() and owned:
                        await _close_resource(handler)
                finally:
                    self._active_scopes.discard(scope_token)
                    if not self._active_scopes:
                        self._scopes_empty.set()

        return scope()

    async def close(self, *, timeout: float | None = None) -> None:
        """Close app-scoped resources in reverse registration order."""

        if self._closed:
            return
        self._closing = True
        deadline = _deadline(timeout)
        if self._active_scopes:
            try:
                remaining = _remaining(deadline)
                if remaining is None:
                    await self._scopes_empty.wait()
                else:
                    await asyncio.wait_for(self._scopes_empty.wait(), remaining)
            except TimeoutError as error:
                self._closed = True
                self._schedule_deferred_cleanup()
                raise TimeoutError(
                    "handler scopes did not finish before shutdown"
                ) from error
            except asyncio.CancelledError:
                self._closed = True
                self._schedule_deferred_cleanup()
                raise
        self._closed = True
        first_error: BaseException | None = None
        resources = tuple(
            resource for _, resource in reversed(tuple(self._app_resources.values()))
        )
        for index, resource in enumerate(resources):
            remaining = _remaining(deadline)
            if remaining is not None and remaining <= 0:
                self._schedule_deferred_cleanup(resources[index:])
                raise TimeoutError("handler resources did not close before shutdown")
            close_task = asyncio.create_task(_close_resource(resource))
            try:
                done, _ = await asyncio.wait({close_task}, timeout=remaining)
            except asyncio.CancelledError:
                self._schedule_deferred_cleanup(resources[index:], close_task)
                raise
            if not done:
                self._schedule_deferred_cleanup(resources[index:], close_task)
                raise TimeoutError("handler resources did not close before shutdown")
            try:
                await close_task
            except asyncio.CancelledError:
                self._schedule_deferred_cleanup(resources[index:])
                raise
            except BaseException as error:
                if first_error is None:
                    first_error = error
        self._app_resources.clear()
        if first_error is not None:
            raise first_error

    def _schedule_deferred_cleanup(
        self,
        resources: tuple[object, ...] | None = None,
        pending_close: asyncio.Task[None] | None = None,
    ) -> None:
        if resources is None:
            resources = tuple(
                resource
                for _, resource in reversed(tuple(self._app_resources.values()))
            )
        cleanup = asyncio.create_task(
            self._finish_deferred_cleanup(resources, pending_close)
        )
        cleanup.add_done_callback(_observe_cleanup_task)

    async def _finish_deferred_cleanup(
        self,
        resources: tuple[object, ...],
        pending_close: asyncio.Task[None] | None,
    ) -> None:
        if self._active_scopes:
            await self._scopes_empty.wait()
        pending_failed = False
        if pending_close is not None:
            try:
                await pending_close
            except BaseException:
                pending_failed = True
                logger.exception("Deferred handler resource cleanup failed")
        start = 0 if pending_close is None or pending_failed else 1
        for resource in resources[start:]:
            try:
                await _close_resource(resource)
            except BaseException:
                logger.exception("Deferred handler resource cleanup failed")
        self._app_resources.clear()

    async def _resolve(self, registration: RegisteredHandler) -> tuple[object, bool]:
        target = registration.target
        app_resource = self._app_resources.get(id(target))
        if app_resource is not None and app_resource[0] is target:
            return app_resource[1], False
        if registration.target_mode in {TargetMode.INSTANCE, TargetMode.FUNCTION}:
            return target, False
        if not callable(target):
            raise TypeError("handler target must be callable")
        if registration.target_mode is TargetMode.CLASS:
            resolved = self._construct(target)
        else:
            resolved = cast(Callable[[], object], target)()
        if inspect.isawaitable(resolved):
            resolved = await resolved
        return resolved, True

    def _construct(self, target: object) -> object:
        class_target = cast(type[object], target)
        parameters = inspect.signature(class_target).parameters.values()
        try:
            annotations = get_type_hints(
                class_target.__init__,
                include_extras=True,
            )
        except NameError, TypeError, ValueError:
            annotations = {}
        arguments: dict[str, object] = {}
        missing = object()
        for parameter in parameters:
            if parameter.kind in {
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            }:
                continue
            annotation = annotations.get(parameter.name, parameter.annotation)
            dependency = self._dependencies.get(annotation, missing)
            if dependency is not missing:
                arguments[parameter.name] = dependency
            elif parameter.default is inspect.Parameter.empty:
                for key, resource in self._app_resources.values():
                    if key is annotation:
                        arguments[parameter.name] = resource
                        break
                else:
                    raise TypeError(
                        f"no explicit dependency for handler parameter {parameter.name}"
                    )
        return cast(Callable[..., object], class_target)(**arguments)


async def _close_resource(resource: object) -> None:
    closer = getattr(resource, "aclose", None)
    if not callable(closer):
        closer = getattr(resource, "close", None)
    if not callable(closer):
        return
    result = closer()
    if inspect.isawaitable(result):
        await result


def _deadline(timeout: float | None) -> float | None:
    if timeout is None:
        return None
    return asyncio.get_running_loop().time() + timeout


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    return max(0.0, deadline - asyncio.get_running_loop().time())


def _observe_cleanup_task(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "Deferred handler resource cleanup task failed",
            exc_info=(type(error), error, error.__traceback__),
        )
