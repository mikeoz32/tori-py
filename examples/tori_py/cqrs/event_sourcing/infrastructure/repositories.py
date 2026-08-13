"""Request-scoped typed repository composition."""

from tori_py_cqrs_event_sourcing import aggregate_repository
from tori_py_cqrs_event_sourcing_core import (
    EventSchemaRegistry,
    EventSourcedRepository,
    EventSourcingUnitOfWork,
)

from examples.tori_py.cqrs.event_sourcing.domain.group import Group
from examples.tori_py.cqrs.event_sourcing.domain.member import Member
from examples.tori_py.cqrs.event_sourcing.domain.post import Post


@aggregate_repository(Member, category="member")
class MemberRepository(EventSourcedRepository[int, Member]):
    pass


@aggregate_repository(Group, category="group")
class GroupRepository(EventSourcedRepository[int, Group]):
    pass


@aggregate_repository(Post, category="post")
class PostRepository(EventSourcedRepository[int, Post]):
    pass


class CommunityRepositories:
    """Low-level repository composition for framework-neutral contract tests."""

    def __init__(
        self,
        unit_of_work: EventSourcingUnitOfWork,
        schemas: EventSchemaRegistry,
    ) -> None:
        self.members = EventSourcedRepository(
            unit_of_work,
            category="member",
            aggregate_factory=Member,
            aggregate_type=Member,
            id_encoder=str,
            schemas=schemas,
        )
        self.groups = EventSourcedRepository(
            unit_of_work,
            category="group",
            aggregate_factory=Group,
            aggregate_type=Group,
            id_encoder=str,
            schemas=schemas,
        )
        self.posts = EventSourcedRepository(
            unit_of_work,
            category="post",
            aggregate_factory=Post,
            aggregate_type=Post,
            id_encoder=str,
            schemas=schemas,
        )


__all__ = [
    "CommunityRepositories",
    "GroupRepository",
    "MemberRepository",
    "PostRepository",
]
