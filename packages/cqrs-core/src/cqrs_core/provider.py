"""Minimal core handler provider without dependency injection."""

import inspect
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import cast

from cqrs_core.errors import InvalidHandlerRegistrationError
from cqrs_core.protocols import DispatchContext, HandlerRegistration
from cqrs_core.registrations import RegisteredHandler, TargetMode


class DefaultHandlerProvider:
    """Resolve explicit instances, classes, functions, and factories.

    This provider does not inspect constructors or resolve dependencies. Classes
    and factories are called without arguments; applications needing a richer
    lifecycle must provide an adapter-specific provider.
    """

    def provide(
        self,
        registration: HandlerRegistration,
        context: DispatchContext,
    ) -> AbstractAsyncContextManager[object]:
        del context
        registered = cast(RegisteredHandler, registration)

        @asynccontextmanager
        async def scope() -> AsyncIterator[object]:
            yield await self._resolve(registered)

        return scope()

    async def _resolve(self, registration: RegisteredHandler) -> object:
        target = registration.target
        if registration.target_mode in {
            TargetMode.INSTANCE,
            TargetMode.FUNCTION,
        }:
            return target

        if not callable(target):
            raise InvalidHandlerRegistrationError("handler target must be callable")

        try:
            factory = cast(Callable[[], object], target)
            resolved = factory()
            if inspect.isawaitable(resolved):
                resolved = await resolved
        except Exception as error:
            raise InvalidHandlerRegistrationError(
                "handler class or factory could not be created"
            ) from error
        return resolved
