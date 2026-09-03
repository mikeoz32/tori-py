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
    delete,
    get,
    injectable,
    module,
    patch,
    post,
    status,
    use_guard,
)
from tori_py.http import HttpException, MsgspecValidationPipe
from tori_py.starlette import RequestContext, StarletteAdapter
from tori_py_liveview import LiveViewModule, LiveViewOptions
from tori_py_microservices import (
    ClientsModule,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    RemoteRpcError,
)

from ..common.contracts import (
    MAX_RESOURCE_OFFSET,
    AuditEntry,
    Availability,
    Booking,
    CancelBookingRequest,
    CleanupOutboxRequest,
    CreateBookingRequest,
    CreateRecurringBookingRequest,
    CreateResource,
    FacilityDashboard,
    Notification,
    OfficePolicy,
    OfficePolicyUpdate,
    OutboxDiagnostics,
    Principal,
    RescheduleBookingRequest,
    Resource,
    UpdateResource,
)
from ..common.infrastructure import rabbitmq_url
from ..common.security import has_workplace_role, is_facilities_admin
from ..common.services import BookingsService, NotificationsService, SpacesService
from .live import WorkplaceLive

WEB_ROOT = FilePath(__file__).resolve().parents[1] / "web"
WEB_ASSETS = frozenset(
    {
        "admin-panel.js",
        "api-client.js",
        "app.js",
        "auth.js",
        "booking-calendar.js",
        "booking-list.js",
        "calendar.js",
        "floor-plan.js",
        "live-shell.css",
        "styles.css",
        "workplace-app.js",
    }
)
VENDOR_ASSETS = frozenset({"keycloak.js", "lit-core.min.js"})
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
    """Serve only declared files needed by the no-build browser client."""

    @get("/")
    async def root(self) -> Response:
        return RedirectResponse("/web/")

    @get("/web/")
    async def index(self) -> Response:
        return FileResponse(WEB_ROOT / "index.html")

    @get("/web/{asset_name}")
    async def web_asset(
        self, asset_name: Annotated[str, Path("asset_name")]
    ) -> Response:
        if asset_name not in WEB_ASSETS:
            raise HttpException(404, "Web asset was not found.")
        media_type = "text/css" if asset_name.endswith(".css") else "text/javascript"
        return FileResponse(WEB_ROOT / asset_name, media_type=media_type)

    @get("/assets/{asset_name}")
    async def vendor_asset(
        self, asset_name: Annotated[str, Path("asset_name")]
    ) -> Response:
        if asset_name not in VENDOR_ASSETS:
            raise HttpException(404, "Vendor asset was not found.")
        return FileResponse(
            WEB_ROOT / "assets" / asset_name, media_type="text/javascript"
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
        self,
        context: Annotated[RequestContext, Context()],
        office_id: Annotated[str | None, Query("office_id")] = None,
        floor_id: Annotated[str | None, Query("floor_id")] = None,
        kind: Annotated[str | None, Query("kind")] = None,
        equipment: Annotated[str | tuple[str, ...], Query("equipment")] = (),
        min_capacity: Annotated[int | None, Query("min_capacity")] = None,
        include_inactive: Annotated[bool, Query("include_inactive")] = False,
        availability_from: Annotated[
            datetime | None, Query("availability_from")
        ] = None,
        availability_to: Annotated[datetime | None, Query("availability_to")] = None,
        offset: Annotated[int, Query("offset")] = 0,
        limit: Annotated[int, Query("limit")] = 50,
    ) -> list[Resource]:
        principal = _principal(context)
        if not 0 <= offset <= MAX_RESOURCE_OFFSET or not 1 <= limit <= 100:
            raise HttpException(400, "Resource page is outside the supported range.")
        if include_inactive:
            _require_admin(principal)
        if (availability_from is None) != (availability_to is None):
            raise HttpException(400, "Availability interval requires both timestamps.")
        if availability_from is not None and availability_to is not None:
            _validate_availability_interval(availability_from, availability_to)
        equipment_filter = (equipment,) if isinstance(equipment, str) else equipment
        if availability_from is None or availability_to is None:
            return await _dispatch(
                self._spaces.list_resources(
                    principal,
                    office_id,
                    floor_id,
                    kind,
                    equipment_filter,
                    min_capacity,
                    include_inactive,
                    offset,
                    limit,
                )
            )
        available_resources: list[Resource] = []
        candidate_offset = 0
        batch_size = 100
        page_end = offset + limit
        while len(available_resources) < page_end:
            candidates = await _dispatch(
                self._spaces.list_resources(
                    principal,
                    office_id,
                    floor_id,
                    kind,
                    equipment_filter,
                    min_capacity,
                    include_inactive,
                    candidate_offset,
                    batch_size,
                )
            )
            if not candidates:
                break
            availability = await _dispatch(
                self._bookings.availability(
                    principal,
                    availability_from,
                    availability_to,
                    None,
                    tuple(resource.id for resource in candidates),
                )
            )
            available_ids = {
                item.resource_id for item in availability if item.available
            }
            available_resources.extend(
                resource for resource in candidates if resource.id in available_ids
            )
            candidate_offset += len(candidates)
            if len(candidates) < batch_size:
                break
        return available_resources[offset:page_end]

    @get("/offices/{office_id}/policy")
    async def get_office_policy(
        self,
        office_id: Annotated[str, Path("office_id")],
        context: Annotated[RequestContext, Context()],
    ) -> OfficePolicy:
        return await _dispatch(
            self._spaces.get_office_policy(_principal(context), office_id)
        )

    @patch("/offices/{office_id}/policy")
    async def update_office_policy(
        self,
        office_id: Annotated[str, Path("office_id")],
        body: Annotated[OfficePolicyUpdate, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> OfficePolicy:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(
            self._spaces.update_office_policy(principal, office_id, body)
        )

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

    @patch("/resources/{resource_id}")
    async def update_resource(
        self,
        resource_id: Annotated[str, Path("resource_id")],
        body: Annotated[UpdateResource, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> Resource:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(
            self._spaces.update_resource(principal, resource_id, body)
        )

    @delete("/resources/{resource_id}")
    async def deactivate_resource(
        self,
        resource_id: Annotated[str, Path("resource_id")],
        context: Annotated[RequestContext, Context()],
    ) -> Resource:
        principal = _principal(context)
        _require_admin(principal)
        return await _dispatch(
            self._spaces.update_resource(
                principal, resource_id, UpdateResource(active=False)
            )
        )

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

    @post("/bookings/recurring")
    @status(201)
    async def create_recurring_booking(
        self,
        body: Annotated[CreateRecurringBookingRequest, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> list[Booking]:
        idempotency_key = context.headers.get("idempotency-key", "")
        if not idempotency_key:
            raise HttpException(400, "Idempotency-Key is required.")
        return await _dispatch(
            self._bookings.create_recurring_booking(
                _principal(context),
                body.resource_id,
                body.starts_at,
                body.ends_at,
                body.recurrence,
                body.occurrence_count,
                idempotency_key,
            )
        )

    @post("/bookings/{booking_id}/reschedule")
    async def reschedule_booking(
        self,
        booking_id: Annotated[str, Path("booking_id")],
        body: Annotated[RescheduleBookingRequest, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> Booking:
        idempotency_key = context.headers.get("idempotency-key", "")
        if not idempotency_key:
            raise HttpException(400, "Idempotency-Key is required.")
        return await _dispatch(
            self._bookings.reschedule_booking(
                _principal(context),
                booking_id,
                body.starts_at,
                body.ends_at,
                idempotency_key,
            )
        )

    @post("/bookings/{booking_id}/cancel")
    async def cancel_booking(
        self,
        booking_id: Annotated[str, Path("booking_id")],
        body: Annotated[CancelBookingRequest, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> list[Booking]:
        idempotency_key = context.headers.get("idempotency-key", "")
        if not idempotency_key:
            raise HttpException(400, "Idempotency-Key is required.")
        return await _dispatch(
            self._bookings.cancel_booking(
                _principal(context), booking_id, body.scope, idempotency_key
            )
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
gateway_liveview = LiveViewModule.for_root(
    LiveViewOptions(
        secret=os.getenv(
            "WORKPLACE_LIVEVIEW_SECRET",
            "workplace-liveview-demo-secret-000000",
        )
    ),
    pages=(WorkplaceLive,),
    imports=(gateway_clients,),
    key="workplace",
)


@module(
    imports=(gateway_clients, gateway_liveview),
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
