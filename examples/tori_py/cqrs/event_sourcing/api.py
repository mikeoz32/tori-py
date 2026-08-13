"""HTTP adapter for the event-sourced community application."""

from typing import Annotated

import msgspec
from tori_py import (
    Body,
    Context,
    Path,
    PipelineResult,
    Query,
    controller,
    get,
    post,
    status,
    use_guard,
)
from tori_py.http import HttpException
from tori_py.starlette import RequestContext, current_request_context
from tori_py.starlette.errors import problem_response
from tori_py_cqrs_core import CommandBus, QueryBus
from tori_py_cqrs_event_sourcing_core import (
    AggregateNotFoundError,
    OptimisticConcurrencyError,
)

from examples.tori_py.cqrs.event_sourcing.application.messages import (
    ChangeDisplayName,
    CreateGroup,
    GetGroup,
    GetMember,
    GroupView,
    HidePost,
    JoinGroup,
    ListGroupPosts,
    MembershipRequestView,
    MemberView,
    PostView,
    PublishPost,
    RegisteredMemberView,
    RegisterMember,
    ReviewMembership,
    SuspendMember,
)
from examples.tori_py.cqrs.event_sourcing.application.projection import (
    ProjectionUnavailableError,
)
from examples.tori_py.cqrs.event_sourcing.domain.shared import (
    AccessDeniedError,
    DomainNotFoundError,
    DomainValidationError,
    GroupAccess,
    Visibility,
)
from examples.tori_py.cqrs.event_sourcing.infrastructure.services import CredentialStore


class RegisterMemberBody(msgspec.Struct, forbid_unknown_fields=True):
    handle: str
    display_name: str
    visibility: Visibility = Visibility.MEMBERS


class ChangeDisplayNameBody(msgspec.Struct, forbid_unknown_fields=True):
    display_name: str


class SuspendMemberBody(msgspec.Struct, forbid_unknown_fields=True):
    reason: str


class CreateGroupBody(msgspec.Struct, forbid_unknown_fields=True):
    name: str
    access: GroupAccess = GroupAccess.PRIVATE


class ReviewMembershipBody(msgspec.Struct, forbid_unknown_fields=True):
    approve: bool
    reason: str | None = None


class PublishPostBody(msgspec.Struct, forbid_unknown_fields=True):
    title: str
    body: str


class HidePostBody(msgspec.Struct, forbid_unknown_fields=True):
    reason: str


class AuthenticationGuard:
    """Resolve a bearer credential into trusted request-state principal data."""

    def __init__(self, credentials: CredentialStore) -> None:
        self._credentials = credentials

    async def can_activate(self, context) -> bool:
        del context
        request_context = current_request_context()
        if request_context is None:
            return False
        request = request_context.request
        actor_id = self._credentials.authenticate(request)
        if actor_id is None:
            return False
        request.state.actor_id = actor_id
        return True


@controller("/community")
class CommunityController:
    def __init__(
        self,
        commands: CommandBus,
        queries: QueryBus,
        credentials: CredentialStore,
    ) -> None:
        self._commands = commands
        self._queries = queries
        self._credentials = credentials

    @staticmethod
    def _actor(context: RequestContext) -> int:
        actor_id = getattr(context.request.state, "actor_id", None)
        if not isinstance(actor_id, int) or isinstance(actor_id, bool) or actor_id < 1:
            raise HttpException(403, "valid authentication is required")
        return actor_id

    @post("/members")
    @status(201)
    async def register_member(
        self,
        body: Annotated[RegisterMemberBody, Body()],
    ) -> RegisteredMemberView:
        member = await self._commands.execute(
            RegisterMember(body.handle, body.display_name, body.visibility)
        )
        return RegisteredMemberView(member, self._credentials.issue(member.id))

    @post("/members/{member_id}/display-name")
    @use_guard("authenticated")
    async def change_display_name(
        self,
        member_id: Annotated[int, Path("member_id")],
        body: Annotated[ChangeDisplayNameBody, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> MemberView:
        return await self._commands.execute(
            ChangeDisplayName(self._actor(context), member_id, body.display_name)
        )

    @post("/members/{member_id}/suspend")
    @use_guard("authenticated")
    async def suspend_member(
        self,
        member_id: Annotated[int, Path("member_id")],
        body: Annotated[SuspendMemberBody, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> MemberView:
        return await self._commands.execute(
            SuspendMember(self._actor(context), member_id, body.reason)
        )

    @get("/members/{member_id}")
    async def get_member(
        self,
        member_id: Annotated[int, Path("member_id")],
        context: Annotated[RequestContext, Context()],
    ) -> MemberView:
        viewer_id = self._credentials.authenticate(context.request)
        return await self._queries.execute(GetMember(member_id, viewer_id))

    @post("/groups")
    @status(201)
    @use_guard("authenticated")
    async def create_group(
        self,
        body: Annotated[CreateGroupBody, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> GroupView:
        return await self._commands.execute(
            CreateGroup(self._actor(context), body.name, body.access)
        )

    @post("/groups/{group_id}/join")
    @use_guard("authenticated")
    async def join_group(
        self,
        group_id: Annotated[int, Path("group_id")],
        context: Annotated[RequestContext, Context()],
    ) -> GroupView | MembershipRequestView:
        return await self._commands.execute(JoinGroup(self._actor(context), group_id))

    @post("/groups/{group_id}/memberships/{member_id}/review")
    @use_guard("authenticated")
    async def review_membership(
        self,
        group_id: Annotated[int, Path("group_id")],
        member_id: Annotated[int, Path("member_id")],
        body: Annotated[ReviewMembershipBody, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> GroupView:
        return await self._commands.execute(
            ReviewMembership(
                self._actor(context),
                group_id,
                member_id,
                body.approve,
                body.reason,
            )
        )

    @get("/groups/{group_id}")
    @use_guard("authenticated")
    async def get_group(
        self,
        group_id: Annotated[int, Path("group_id")],
        context: Annotated[RequestContext, Context()],
    ) -> GroupView:
        return await self._queries.execute(GetGroup(group_id, self._actor(context)))

    @post("/groups/{group_id}/posts")
    @status(201)
    @use_guard("authenticated")
    async def publish_post(
        self,
        group_id: Annotated[int, Path("group_id")],
        body: Annotated[PublishPostBody, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> PostView:
        return await self._commands.execute(
            PublishPost(self._actor(context), group_id, body.title, body.body)
        )

    @post("/groups/{group_id}/posts/{post_id}/hide")
    @use_guard("authenticated")
    async def hide_post(
        self,
        group_id: Annotated[int, Path("group_id")],
        post_id: Annotated[int, Path("post_id")],
        body: Annotated[HidePostBody, Body()],
        context: Annotated[RequestContext, Context()],
    ) -> PostView:
        return await self._commands.execute(
            HidePost(self._actor(context), group_id, post_id, body.reason)
        )

    @get("/groups/{group_id}/posts")
    @use_guard("authenticated")
    async def list_posts(
        self,
        group_id: Annotated[int, Path("group_id")],
        context: Annotated[RequestContext, Context()],
        after_id: Annotated[int, Query("after")] = 0,
        limit: Annotated[int, Query("limit")] = 50,
    ) -> list[PostView]:
        return await self._queries.execute(
            ListGroupPosts(
                group_id,
                self._actor(context),
                after_id,
                limit,
            )
        )


class CommunityErrorFilter:
    async def catch(
        self,
        error: Exception,
        context: RequestContext,
    ) -> PipelineResult:
        if isinstance(error, HttpException):
            return PipelineResult.from_response(
                problem_response(
                    error.status_code,
                    error.detail,
                    request=context.request,
                    title=error.title,
                    headers=error.headers,
                    errors=error.errors,
                )
            )
        if isinstance(error, DomainValidationError):
            status_code = 400
            detail = str(error)
        elif isinstance(error, AccessDeniedError):
            status_code = 404
            detail = "resource was not found"
        elif isinstance(error, (AggregateNotFoundError, DomainNotFoundError)):
            status_code = 404
            detail = "resource was not found"
        elif isinstance(error, OptimisticConcurrencyError):
            status_code = 409
            detail = "resource changed; retry from fresh state"
        elif isinstance(error, ProjectionUnavailableError):
            status_code = 503
            detail = "read model is catching up"
        else:
            raise error
        return PipelineResult.from_response(
            problem_response(
                status_code,
                detail,
                request=context.request,
            )
        )


__all__ = [
    "AuthenticationGuard",
    "CommunityController",
    "CommunityErrorFilter",
]
