"""Post aggregate storing only an erasable content-vault reference."""

from dataclasses import dataclass

from cqrs_core import Event
from cqrs_event_sourcing import AggregateRoot

from examples.nestpy.cqrs.event_sourcing.domain.shared import (
    AccessDeniedError,
    require_text,
)


@dataclass(frozen=True, slots=True)
class PostPublished(Event):
    group_id: int
    author_id: int
    title: str
    content_ref: int


@dataclass(frozen=True, slots=True)
class PostEdited(Event):
    actor_id: int
    title: str
    content_ref: int


@dataclass(frozen=True, slots=True)
class PostHidden(Event):
    moderator_id: int
    reason: str


class Post(AggregateRoot[int]):
    """Group post lifecycle with explicit moderation history."""

    def __init__(self, post_id: int) -> None:
        super().__init__(post_id)
        self.group_id = 0
        self.author_id = 0
        self.title = ""
        self.content_ref = 0
        self.hidden = False
        self.hidden_reason: str | None = None

    def publish(
        self,
        *,
        group_id: int,
        author_id: int,
        title: str,
        content_ref: int,
    ) -> None:
        self.raise_event(
            PostPublished(
                group_id=group_id,
                author_id=author_id,
                title=require_text(title, field="post title", maximum=160),
                content_ref=content_ref,
            )
        )

    def edit(
        self,
        *,
        actor_id: int,
        title: str,
        content_ref: int,
    ) -> None:
        if actor_id != self.author_id:
            raise AccessDeniedError("only the author can edit a post")
        self.raise_event(
            PostEdited(
                actor_id=actor_id,
                title=require_text(title, field="post title", maximum=160),
                content_ref=content_ref,
            )
        )

    def hide(self, *, moderator_id: int, reason: str) -> None:
        if self.hidden:
            return
        self.raise_event(
            PostHidden(
                moderator_id=moderator_id,
                reason=require_text(reason, field="moderation reason", maximum=240),
            )
        )

    def _apply(self, event: Event) -> None:
        match event:
            case PostPublished(
                group_id=group_id,
                author_id=author_id,
                title=title,
                content_ref=content_ref,
            ):
                self.group_id = group_id
                self.author_id = author_id
                self.title = title
                self.content_ref = content_ref
            case PostEdited(title=title, content_ref=content_ref):
                self.title = title
                self.content_ref = content_ref
            case PostHidden(reason=reason):
                self.hidden = True
                self.hidden_reason = reason
            case _:
                raise AssertionError(f"unknown post event: {event!r}")


__all__ = ["Post", "PostEdited", "PostHidden", "PostPublished"]
