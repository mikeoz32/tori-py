"""Small app-level authorization example built on method interceptors."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, cast

from tori_py import (
    ClassProvider,
    ExecutionContext,
    HttpResponse,
    Inject,
    MethodInvocationContext,
    NestApplication,
    Path,
    PipelineResult,
    Scope,
    WorkScopeFactory,
    controller,
    get,
    injectable,
    module,
    post,
    use_filter,
    use_guard,
    use_method_interceptor,
)
from tori_py.starlette import RequestContext, StarletteAdapter


@dataclass(frozen=True, slots=True)
class CallerContext:
    subject: str
    permissions: frozenset[str]


class CallerScope:
    """Per-request/work-scope caller established by a trusted entry point."""

    def __init__(self) -> None:
        self._caller: CallerContext | None = None

    def bind(self, caller: CallerContext) -> None:
        if self._caller is not None:
            raise RuntimeError("caller is already bound")
        self._caller = caller

    @property
    def caller(self) -> CallerContext:
        if self._caller is None:
            raise RuntimeError("caller has not been authenticated")
        return self._caller


class PermissionDenied(Exception):
    """The authenticated caller does not have the required permission."""


@dataclass(frozen=True, slots=True)
class RequirePermission:
    permission: str

    async def intercept(
        self,
        context: MethodInvocationContext,
        next: Callable[[], Awaitable[object]],
    ) -> object:
        caller_scope = cast(
            CallerScope,
            await context.resolver.resolve(CallerScope),
        )
        if self.permission not in caller_scope.caller.permissions:
            raise PermissionDenied(self.permission)
        return await next()


def requires_permission(permission: str):
    """Application decorator sugar over Tori Py's method interceptor binding."""

    if not permission:
        raise ValueError("permission must not be empty")
    return use_method_interceptor(RequirePermission(permission))


_DEMO_CALLERS = {
    "reader-token": CallerContext("reader", frozenset({"documents:read"})),
    "publisher-token": CallerContext(
        "publisher",
        frozenset({"documents:read", "documents:publish"}),
    ),
}


class DemoBearerGuard:
    """Demo authentication boundary; replace the fixed tokens in real apps."""

    def __init__(
        self,
        caller_scope: Annotated[CallerScope, Inject(CallerScope)],
    ) -> None:
        self._caller_scope = caller_scope

    async def can_activate(self, context: ExecutionContext) -> bool:
        request_context = cast(RequestContext, context)
        authorization = request_context.headers.get("authorization", "")
        scheme, separator, token = authorization.partition(" ")
        caller = (
            _DEMO_CALLERS.get(token)
            if separator and scheme.casefold() == "bearer"
            else None
        )
        if caller is None:
            return False
        self._caller_scope.bind(caller)
        return True


class PermissionDeniedFilter:
    async def catch(
        self, error: Exception, context: ExecutionContext
    ) -> PipelineResult:
        del context
        if not isinstance(error, PermissionDenied):
            raise error
        return PipelineResult.from_response(
            HttpResponse(
                b'{"detail":"Permission denied."}',
                status_code=403,
                headers={"content-type": "application/json"},
            )
        )


@injectable(proxy=True)
class DocumentService:
    @requires_permission("documents:read")
    async def read(self, document_id: str) -> dict[str, str]:
        return {"id": document_id, "body": "example document"}

    @requires_permission("documents:publish")
    async def publish(self, document_id: str) -> dict[str, str]:
        return {"id": document_id, "status": "published"}


class InProcessDocumentActions:
    """Example entry point for LiveView or another in-process caller."""

    def __init__(self, scopes: WorkScopeFactory) -> None:
        self._scopes = scopes

    async def publish(
        self,
        caller: CallerContext,
        document_id: str,
    ) -> dict[str, str]:
        async def invoke(resolver) -> dict[str, str]:
            caller_scope = cast(CallerScope, await resolver.resolve(CallerScope))
            caller_scope.bind(caller)
            documents = cast(DocumentService, await resolver.resolve(DocumentService))
            return await documents.publish(document_id)

        return await self._scopes.run(invoke)


@controller("/documents")
@use_guard(DemoBearerGuard)
@use_filter(PermissionDeniedFilter())
class DocumentsController:
    def __init__(self, documents: DocumentService) -> None:
        self._documents = documents

    @get("/{document_id}")
    async def read(
        self,
        document_id: Annotated[str, Path("document_id")],
    ) -> dict[str, str]:
        return await self._documents.read(document_id)

    @post("/{document_id}/publish")
    async def publish(
        self,
        document_id: Annotated[str, Path("document_id")],
    ) -> dict[str, str]:
        return await self._documents.publish(document_id)


@module(
    controllers=[DocumentsController],
    providers=[
        ClassProvider(CallerScope, scope=Scope.REQUEST),
        ClassProvider(DemoBearerGuard, scope=Scope.REQUEST),
        DocumentService,
        ClassProvider(InProcessDocumentActions),
    ],
)
class AuthorizationExampleModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AuthorizationExampleModule,
        adapter=StarletteAdapter(),
    )
