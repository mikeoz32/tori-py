"""Authenticated HTTP edge and explicit static assets for Tori Space."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable
from datetime import datetime
from pathlib import Path as FilePath
from typing import Annotated, Any

import jwt
from jwt import PyJWKClient
from starlette.responses import FileResponse, RedirectResponse, Response
from tori_py import (
    Body,
    Context,
    NestApplication,
    Path,
    Query,
    ValueProvider,
    controller,
    get,
    injectable,
    module,
    post,
    status,
    use_guard,
)
from tori_py.http import HttpException, MsgspecValidationPipe
from tori_py.starlette import RequestContext, StarletteAdapter
from tori_py_microservices import (
    ClientsModule,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    RemoteRpcError,
)

from ..common.contracts import (
    AuditEntry,
    Availability,
    Booking,
    CleanupOutboxRequest,
    CreateBookingRequest,
    CreateResource,
    FacilityDashboard,
    Notification,
    OutboxDiagnostics,
    Principal,
    Resource,
)
from ..common.infrastructure import rabbitmq_url
from ..common.security import has_workplace_role, is_facilities_admin
from ..common.services import BookingsService, NotificationsService, SpacesService

WEB_ROOT = FilePath(__file__).resolve().parents[1] / "web"
logger = logging.getLogger(__name__)


@injectable()
class KeycloakBearerGuard:
    """Validate a browser token and expose only trusted identity state."""

    def __init__(
        self,
        issuer: str | None = None,
        audience: str | None = None,
        jwks_client: PyJWKClient | None = None,
    ) -> None:
        self._issuer = issuer or os.getenv("KEYCLOAK_ISSUER")
        self._audience = audience or os.getenv("KEYCLOAK_AUDIENCE")
        jwks_url = os.getenv("KEYCLOAK_JWKS_URL")
        self._jwks = jwks_client or (
            PyJWKClient(jwks_url or f"{self._issuer}/protocol/openid-connect/certs")
            if self._issuer
            else None
        )

    async def can_activate(self, context: RequestContext) -> bool:
        authorization = context.headers.get("authorization", "")
        principal = await asyncio.to_thread(self.principal, authorization)
        if not has_workplace_role(principal):
            raise HttpException(403, "A workplace role is required.")
        context.request.state.principal = principal
        return True

    def principal(self, authorization: str) -> Principal:
        if (
            not self._issuer
            or not self._audience
            or self._jwks is None
            or not authorization.startswith("Bearer ")
        ):
            raise HttpException(401, "Authentication is required.")
        token = authorization.removeprefix("Bearer ")
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self._issuer,
                audience=self._audience,
                options={"require": ["exp", "iss", "sub", "aud"]},
            )
            return _principal_from_claims(claims)
        except HttpException:
            raise
        except Exception as error:
            raise HttpException(401, "Invalid bearer token.") from error


@controller()
class StaticController:
    """Serve only the four files needed by the no-build browser client."""

    @get("/")
    async def root(self) -> Response:
        return RedirectResponse("/web/")

    @get("/web/")
    async def index(self) -> Response:
        return FileResponse(WEB_ROOT / "index.html")

    @get("/web/styles.css")
    async def styles(self) -> Response:
        return FileResponse(WEB_ROOT / "styles.css", media_type="text/css")

    @get("/web/app.js")
    async def application_script(self) -> Response:
        return FileResponse(WEB_ROOT / "app.js", media_type="text/javascript")

    @get("/assets/keycloak.js")
    async def keycloak_script(self) -> Response:
        return FileResponse(
            WEB_ROOT / "assets" / "keycloak.js", media_type="text/javascript"
        )


@controller("/api")
@use_guard(KeycloakBearerGuard)
class GatewayController:
    def __init__(
        self,
        spaces: SpacesService,
        bookings: BookingsService,
        notifications: NotificationsService,
    ) -> None:
        self._spaces = spaces
        self._bookings = bookings
        self._notifications = notifications

    @get("/resources")
    async def list_resources(
        self, context: Annotated[RequestContext, Context()]
    ) -> list[Resource]:
        return await _dispatch(self._spaces.list_resources(_principal(context)))

    @post("/resources")
    @status(201)
    async def create_resource(
        self,
        body: Annotated[CreateResource, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> Resource:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(self._spaces.create_resource(principal, body))

    @get("/bookings")
    async def list_bookings(
        self,
        context: Annotated[RequestContext, Context()],
        resource_id: Annotated[str | None, Query("resource_id")] = None,
        starts_at: Annotated[datetime | None, Query("starts_at")] = None,
        ends_at: Annotated[datetime | None, Query("ends_at")] = None,
        offset: Annotated[int, Query("offset")] = 0,
        limit: Annotated[int, Query("limit")] = 100,
    ) -> list[Booking]:
        if offset < 0 or not 1 <= limit <= 500:
            raise HttpException(400, "Booking page is outside the supported range.")
        return await _dispatch(
            self._bookings.list_bookings(
                _principal(context), resource_id, starts_at, ends_at, offset, limit
            )
        )

    @get("/availability")
    async def availability(
        self,
        starts_at: Annotated[datetime, Query("starts_at")],
        ends_at: Annotated[datetime, Query("ends_at")],
        context: Annotated[RequestContext, Context()],
        resource_id: Annotated[str | None, Query("resource_id")] = None,
    ) -> list[Availability]:
        _validate_availability_interval(starts_at, ends_at)
        return await _dispatch(
            self._bookings.availability(
                _principal(context), starts_at, ends_at, resource_id
            )
        )

    @get("/facilities/dashboard")
    async def facilities_dashboard(
        self, context: Annotated[RequestContext, Context()]
    ) -> FacilityDashboard:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(self._bookings.facilities_dashboard(principal))

    @get("/audit")
    async def list_audit(
        self,
        context: Annotated[RequestContext, Context()],
        starts_at: Annotated[datetime | None, Query("starts_at")] = None,
        ends_at: Annotated[datetime | None, Query("ends_at")] = None,
        resource_id: Annotated[str | None, Query("resource_id")] = None,
    ) -> list[AuditEntry]:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(
            self._bookings.list_audit(principal, starts_at, ends_at, resource_id)
        )

    @get("/outbox/diagnostics")
    async def outbox_diagnostics(
        self, context: Annotated[RequestContext, Context()]
    ) -> OutboxDiagnostics:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(self._bookings.outbox_diagnostics(principal))

    @post("/outbox/cleanup")
    async def cleanup_outbox(
        self,
        body: Annotated[CleanupOutboxRequest, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> int:
        principal = _principal(context)
        _require_admin(principal)
        _validate_utc_timestamp(body.before, "Cleanup timestamp")
        return await _dispatch(self._bookings.cleanup_outbox(principal, body.before))

    @get("/bookings/{booking_id}")
    async def get_booking(
        self,
        booking_id: Annotated[str, Path("booking_id")],
        context: Annotated[RequestContext, Context()],
    ) -> Booking:
        return await _dispatch(
            self._bookings.get_booking(_principal(context), booking_id)
        )

    @post("/bookings")
    @status(201)
    async def create_booking(
        self,
        body: Annotated[CreateBookingRequest, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> Booking:
        idempotency_key = context.headers.get("idempotency-key", "")
        if not idempotency_key:
            raise HttpException(400, "Idempotency-Key is required.")
        return await _dispatch(
            self._bookings.create_booking(
                _principal(context),
                body.resource_id,
                body.starts_at,
                body.ends_at,
                idempotency_key,
            )
        )

    @post("/bookings/{booking_id}/cancel")
    async def cancel_booking(
        self,
        booking_id: Annotated[str, Path("booking_id")],
        context: Annotated[RequestContext, Context()],
    ) -> Booking:
        return await _dispatch(
            self._bookings.cancel_booking(_principal(context), booking_id)
        )

    @post("/bookings/{booking_id}/check-in")
    async def check_in_booking(
        self,
        booking_id: Annotated[str, Path("booking_id")],
        context: Annotated[RequestContext, Context()],
    ) -> Booking:
        return await _dispatch(
            self._bookings.check_in_booking(_principal(context), booking_id)
        )

    @get("/notifications")
    async def list_notifications(
        self, context: Annotated[RequestContext, Context()]
    ) -> list[Notification]:
        return await _dispatch(
            self._notifications.list_notifications(_principal(context))
        )


@controller()
class OperationsController:
    def __init__(
        self,
        spaces: SpacesService,
        bookings: BookingsService,
        notifications: NotificationsService,
    ) -> None:
        self._spaces = spaces
        self._bookings = bookings
        self._notifications = notifications

    @get("/health")
    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

    @get("/ready")
    async def ready(self) -> dict[str, str]:
        try:
            await asyncio.gather(
                self._spaces.health(),
                self._bookings.health(),
                self._notifications.health(),
            )
        except Exception as error:
            raise HttpException(503, "Gateway dependencies are not ready.") from error
        return {"status": "ready"}


gateway_reference = RabbitMqTransport()
gateway_rabbit = RabbitMqModule.for_root(RabbitMqOptions(rabbitmq_url("gateway")))
gateway_clients = ClientsModule.register_cluster(
    gateway_reference,
    imports=(gateway_rabbit,),
    contracts=(SpacesService, BookingsService, NotificationsService),
)


@module(
    imports=(gateway_clients,),
    providers=(
        ValueProvider("validation", MsgspecValidationPipe()),
        KeycloakBearerGuard,
    ),
    controllers=(StaticController, GatewayController, OperationsController),
)
class GatewayAppModule:
    pass


async def create_application() -> NestApplication:
    application = await NestApplication.create(
        GatewayAppModule, adapter=StarletteAdapter()
    )
    application.use_global_pipe("validation")
    return application


def _principal(context: RequestContext) -> Principal:
    principal = getattr(context.request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HttpException(401, "Authentication is required.")
    return principal


def _principal_from_claims(claims: dict[str, Any]) -> Principal:
    tenant_id = claims.get("tenant_id")
    actor_id = claims.get("sub")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise HttpException(401, "The token has no tenant identity.")
    if not isinstance(actor_id, str) or not actor_id:
        raise HttpException(401, "The token has no subject.")

    roles: list[str] = []
    resource_access = claims.get("resource_access")
    if isinstance(resource_access, dict):
        web_access = resource_access.get("tori-space-web")
        if isinstance(web_access, dict):
            role_values = web_access.get("roles")
            if isinstance(role_values, list):
                roles.extend(role for role in role_values if isinstance(role, str))
    return Principal(tenant_id, actor_id, tuple(dict.fromkeys(roles)))


def _require_admin(principal: Principal) -> None:
    if not is_facilities_admin(principal):
        raise HttpException(403, "Facilities administrator role is required.")


def _validate_availability_interval(starts_at: datetime, ends_at: datetime) -> None:
    for value in (starts_at, ends_at):
        _validate_utc_timestamp(value, "Availability timestamp")
    if starts_at >= ends_at:
        raise HttpException(400, "Availability period is invalid.")


def _validate_utc_timestamp(value: datetime, label: str) -> None:
    offset = value.utcoffset()
    if value.tzinfo is None or offset is None or offset.total_seconds() != 0:
        raise HttpException(400, f"{label} must be timezone-aware UTC.")


async def _dispatch[T](request: Awaitable[T]) -> T:
    try:
        return await request
    except RemoteRpcError as error:
        logger.warning(
            "remote RPC failed: code=%s retryable=%s details=%r",
            error.code,
            error.retryable,
            error.details,
        )
        status_code = {
            "invalid_request": 400,
            "forbidden": 403,
            "not_found": 404,
            "conflict": 409,
            "unavailable": 503,
        }.get(error.code, 502)
        raise HttpException(status_code, error.message) from error
