"""End-to-end verification for the large event-sourcing community project."""

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule
from tori_py_cqrs_core import CommandBus, Event, QueryBus
from tori_py_cqrs_event_sourcing import get_event_store_token
from tori_py_cqrs_event_sourcing_core import (
    AppendEvent,
    EncodedEvent,
    EventCodecError,
    EventMetadata,
    EventSchemaRegistry,
    EventSourcingLimits,
    EventSourcingUnitOfWork,
    InMemoryEventStore,
    OptimisticConcurrencyError,
    PendingEvent,
    StreamId,
)

from examples.tori_py.cqrs.event_sourcing.app import (
    AppModule,
    CommunityModule,
    pipeline_options,
)
from examples.tori_py.cqrs.event_sourcing.application.messages import (
    CreateGroup,
    GetGroup,
    HidePost,
    JoinGroup,
    ListGroupPosts,
    PublishPost,
    RegisterMember,
    ReviewMembership,
    SuspendMember,
)
from examples.tori_py.cqrs.event_sourcing.application.projection import (
    CommunityProjection,
    ProjectionUnavailableError,
)
from examples.tori_py.cqrs.event_sourcing.domain.group import Group, GroupCreated
from examples.tori_py.cqrs.event_sourcing.domain.member import MemberRegistered
from examples.tori_py.cqrs.event_sourcing.domain.post import PostPublished
from examples.tori_py.cqrs.event_sourcing.domain.shared import (
    AccessDeniedError,
    DomainNotFoundError,
    GroupAccess,
    Visibility,
)
from examples.tori_py.cqrs.event_sourcing.infrastructure.repositories import (
    CommunityRepositories,
)
from examples.tori_py.cqrs.event_sourcing.infrastructure.schemas import build_schemas
from examples.tori_py.cqrs.event_sourcing.infrastructure.services import (
    ContentVault,
    UnitOfWorkMetrics,
)


async def compile_application():
    return await TestingModule.create(AppModule).compile(
        adapter=StarletteAdapter(),
        pipeline=pipeline_options,
    )


def encode_event(
    schemas: EventSchemaRegistry,
    event: Event,
    *,
    event_id: int,
) -> AppendEvent:
    return schemas.encode(
        PendingEvent(
            event,
            EventMetadata(
                event_id=UUID(int=event_id),
                occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
            ),
        )
    )


@pytest.mark.asyncio
async def test_bus_journey_enforces_membership_privacy_and_moderation() -> None:
    application = await compile_application()
    try:
        commands = await application.resolve(CommandBus)
        queries = await application.resolve(QueryBus)
        store = await application.resolve(
            get_event_store_token(key="community"),
            module=CommunityModule,
        )
        projection = await application.resolve(
            CommunityProjection,
            module=CommunityModule,
        )
        unit_of_work_metrics = await application.resolve(
            UnitOfWorkMetrics,
            module=CommunityModule,
        )
        assert isinstance(commands, CommandBus)
        assert isinstance(queries, QueryBus)
        assert isinstance(store, InMemoryEventStore)
        assert isinstance(projection, CommunityProjection)
        assert isinstance(unit_of_work_metrics, UnitOfWorkMetrics)

        alice = await commands.execute(
            RegisterMember("alice", "Alice", Visibility.PUBLIC)
        )
        bob = await commands.execute(
            RegisterMember("bob_01", "Bob", Visibility.MEMBERS)
        )
        group = await commands.execute(
            CreateGroup(alice.id, "Private Workshop", GroupAccess.PRIVATE)
        )

        pending = await commands.execute(JoinGroup(bob.id, group.id))
        assert pending.status == "pending"
        with pytest.raises(DomainNotFoundError, match="not found"):
            await queries.execute(GetGroup(group.id, bob.id))

        approved = await commands.execute(
            ReviewMembership(alice.id, group.id, bob.id, True)
        )
        assert approved.members == (alice.id, bob.id)

        post = await commands.execute(
            PublishPost(
                bob.id,
                group.id,
                "Consent checklist",
                "A practical checklist stored outside the immutable event stream.",
            )
        )
        assert post.body is not None
        assert await queries.execute(ListGroupPosts(group.id, bob.id)) == [post]

        hidden = await commands.execute(
            HidePost(alice.id, group.id, post.id, "awaiting moderation review")
        )
        assert hidden.hidden
        assert hidden.body is None
        assert await queries.execute(ListGroupPosts(group.id, bob.id)) == []
        moderator_posts = await queries.execute(ListGroupPosts(group.id, alice.id))
        assert moderator_posts == [hidden]
        assert moderator_posts[0].moderation_reason == "awaiting moderation review"

        suspended = await commands.execute(
            SuspendMember(alice.id, bob.id, "temporary safety review")
        )
        assert suspended.suspended
        with pytest.raises(DomainNotFoundError, match="not found"):
            await queries.execute(ListGroupPosts(group.id, bob.id))

        self_suspended = await commands.execute(
            SuspendMember(alice.id, alice.id, "moderator safety review")
        )
        assert self_suspended.suspended
        with pytest.raises(AccessDeniedError, match="suspended"):
            await commands.execute(
                SuspendMember(alice.id, bob.id, "unauthorized follow-up")
            )
        with pytest.raises(DomainNotFoundError, match="not found"):
            await queries.execute(ListGroupPosts(group.id, alice.id))

        committed = await store.read_all(limit=100)
        assert projection.checkpoint == committed[-1].global_position
        assert {event.event.encoded.event_type for event in committed} >= {
            "community.member-registered",
            "community.group-created",
            "community.membership-requested",
            "community.member-joined",
            "community.post-published",
            "community.post-hidden",
        }
        assert unit_of_work_metrics.entries == 10
        assert unit_of_work_metrics.exits == 10
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_http_journey_uses_the_same_commands_queries_and_filters() -> None:
    application = await compile_application()
    try:
        async with application.http_client() as client:
            malformed = await client.post(
                "/community/members",
                json={"handle": 7, "display_name": "invalid"},
            )
            assert malformed.status_code == 400

            alice_response = await client.post(
                "/community/members",
                json={
                    "handle": "alice",
                    "display_name": "Alice",
                    "visibility": "private",
                },
            )
            assert alice_response.status_code == 201
            registration = alice_response.json()
            alice = registration["member"]
            alice_auth = {"authorization": f"Bearer {registration['access_token']}"}

            bob_response = await client.post(
                "/community/members",
                json={"handle": "bob_01", "display_name": "Bob"},
            )
            bob_registration = bob_response.json()
            bob_auth = {"authorization": f"Bearer {bob_registration['access_token']}"}

            missing_credential = await client.post(
                "/community/groups",
                json={"name": "Denied", "access": "public"},
            )
            assert missing_credential.status_code == 403
            forged_credential = await client.post(
                "/community/groups",
                json={"name": "Denied", "access": "public"},
                headers={"authorization": "Bearer forged"},
            )
            assert forged_credential.status_code == 403

            unknown_field = await client.post(
                "/community/groups",
                json={"name": "Denied", "access": "public", "actor_id": alice["id"]},
                headers=alice_auth,
            )
            assert unknown_field.status_code == 400

            private_profile = await client.get(
                f"/community/members/{alice['id']}",
                headers=bob_auth,
            )
            assert private_profile.status_code == 404
            assert private_profile.json()["detail"] == "resource was not found"

            group_response = await client.post(
                "/community/groups",
                json={"name": "Open Workshop", "access": "public"},
                headers=alice_auth,
            )
            assert group_response.status_code == 201
            group = group_response.json()

            joined = await client.post(
                f"/community/groups/{group['id']}/join",
                headers=bob_auth,
            )
            assert joined.status_code == 200
            assert joined.json()["member_count"] == 2
            assert joined.json()["members"] == []

            published = await client.post(
                f"/community/groups/{group['id']}/posts",
                json={"title": "Welcome", "body": "Community guidelines"},
                headers=bob_auth,
            )
            assert published.status_code == 201

            posts = await client.get(
                f"/community/groups/{group['id']}/posts",
                headers=alice_auth,
            )
            assert posts.status_code == 200
            assert posts.json() == [published.json()]
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_historical_member_registration_is_upcast_during_replay() -> None:
    store = InMemoryEventStore()
    schemas = build_schemas()
    historical = AppendEvent(
        EncodedEvent(
            "community.member-registered",
            1,
            json.dumps({"handle": "legacy", "display_name": "Legacy Member"}).encode(),
        ),
        EventMetadata(
            event_id=UUID(int=1),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    async with store.transaction() as transaction:
        transaction.append(
            StreamId("member", "77"),
            expected_version=0,
            events=[historical],
        )
        await transaction.commit()

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        repositories = CommunityRepositories(unit_of_work, schemas)
        member = await repositories.members.get(77)

    assert member.handle == "legacy"
    assert member.visibility is Visibility.MEMBERS
    assert member.version == 1


@pytest.mark.asyncio
async def test_malformed_persisted_event_is_rejected_during_replay() -> None:
    store = InMemoryEventStore()
    schemas = build_schemas()
    malformed = AppendEvent(
        EncodedEvent(
            "community.member-registered",
            2,
            json.dumps(
                {
                    "handle": [],
                    "display_name": "Malformed Member",
                    "visibility": "members",
                }
            ).encode(),
        ),
        EventMetadata(
            event_id=UUID(int=2),
            occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )
    async with store.transaction() as transaction:
        transaction.append(
            StreamId("member", "78"),
            expected_version=0,
            events=[malformed],
        )
        await transaction.commit()

    with pytest.raises(EventCodecError, match="decoder failed"):
        async with EventSourcingUnitOfWork(store) as unit_of_work:
            repositories = CommunityRepositories(unit_of_work, schemas)
            await repositories.members.get(78)


@pytest.mark.asyncio
async def test_projection_budget_fails_closed_and_post_page_stops_at_limit() -> None:
    limits = EventSourcingLimits(read_page_size=1)
    store = InMemoryEventStore(limits=limits)
    schemas = build_schemas(limits)
    content = ContentVault()
    first_content = content.put("visible body")
    erased_later_content = content.put("later erased body")
    content.erase(erased_later_content)

    async with store.transaction() as transaction:
        transaction.append(
            StreamId("member", "1"),
            expected_version=0,
            events=[
                encode_event(
                    schemas,
                    MemberRegistered("alice", "Alice", Visibility.PUBLIC),
                    event_id=10,
                )
            ],
        )
        transaction.append(
            StreamId("group", "1"),
            expected_version=0,
            events=[
                encode_event(
                    schemas,
                    GroupCreated(1, "Bounded", GroupAccess.PUBLIC),
                    event_id=11,
                )
            ],
        )
        transaction.append(
            StreamId("post", "1"),
            expected_version=0,
            events=[
                encode_event(
                    schemas,
                    PostPublished(1, 1, "First", first_content),
                    event_id=12,
                )
            ],
        )
        transaction.append(
            StreamId("post", "2"),
            expected_version=0,
            events=[
                encode_event(
                    schemas,
                    PostPublished(1, 1, "Second", erased_later_content),
                    event_id=13,
                )
            ],
        )
        await transaction.commit()

    projection = CommunityProjection(content)
    with pytest.raises(ProjectionUnavailableError, match="budget"):
        await projection.catch_up(store, schemas, max_pages=1)
    assert projection.checkpoint == 1

    await projection.catch_up(store, schemas)
    posts = projection.posts(1, viewer_id=1, after_id=0, limit=1)
    assert len(posts) == 1
    assert posts[0].title == "First"
    assert posts[0].body == "visible body"


@pytest.mark.asyncio
async def test_stale_group_writer_is_faulted_by_optimistic_concurrency() -> None:
    store = InMemoryEventStore()
    schemas: EventSchemaRegistry = build_schemas()
    group_id = 1

    async with EventSourcingUnitOfWork(store) as initial:
        repositories = CommunityRepositories(initial, schemas)
        group = Group(group_id)
        group.create(owner_id=1, name="Concurrency", access=GroupAccess.PRIVATE)
        repositories.groups.save(group)
        await initial.commit()

    first = EventSourcingUnitOfWork(store)
    second = EventSourcingUnitOfWork(store)
    async with first, second:
        first_repositories = CommunityRepositories(first, schemas)
        second_repositories = CommunityRepositories(second, schemas)
        first_group = await first_repositories.groups.get(group_id)
        second_group = await second_repositories.groups.get(group_id)
        first_group.request_membership(member_id=2)
        second_group.request_membership(member_id=3)
        first_repositories.groups.save(first_group)
        second_repositories.groups.save(second_group)
        await first.commit()
        with pytest.raises(OptimisticConcurrencyError):
            await second.commit()

    assert second_group.is_faulted
    assert second_group.pending_events
