"""Member aggregate and immutable member events."""

import re
from dataclasses import dataclass

from cqrs_core import Event
from cqrs_event_sourcing import AggregateRoot

from examples.nestpy.cqrs.event_sourcing.domain.shared import (
    AccessDeniedError,
    DomainValidationError,
    Visibility,
    require_text,
)

_HANDLE = re.compile(r"[a-z0-9_]{3,24}")


@dataclass(frozen=True, slots=True)
class MemberRegistered(Event):
    handle: str
    display_name: str
    visibility: Visibility


@dataclass(frozen=True, slots=True)
class DisplayNameChanged(Event):
    display_name: str


@dataclass(frozen=True, slots=True)
class MemberSuspended(Event):
    actor_id: int
    reason: str


class Member(AggregateRoot[int]):
    """Profile identity, privacy policy, and account safety state."""

    def __init__(self, member_id: int) -> None:
        super().__init__(member_id)
        self.handle = ""
        self.display_name = ""
        self.visibility = Visibility.MEMBERS
        self.suspended = False
        self.suspension_reason: str | None = None

    def register(
        self,
        *,
        handle: str,
        display_name: str,
        visibility: Visibility,
    ) -> None:
        normalized_handle = handle.strip().lower()
        if not _HANDLE.fullmatch(normalized_handle):
            raise DomainValidationError(
                "handle must contain 3-24 lowercase letters, digits, or underscores"
            )
        name = require_text(display_name, field="display name", maximum=80)
        self.raise_event(MemberRegistered(normalized_handle, name, visibility))

    def change_display_name(self, *, actor_id: int, display_name: str) -> None:
        self.ensure_active()
        if actor_id != self.id:
            raise AccessDeniedError("members can change only their own display name")
        name = require_text(display_name, field="display name", maximum=80)
        if name == self.display_name:
            return
        self.raise_event(DisplayNameChanged(name))

    def suspend(self, *, actor_id: int, reason: str, authorized: bool) -> None:
        if not authorized:
            raise AccessDeniedError("platform moderation permission is required")
        if self.suspended:
            return
        self.raise_event(
            MemberSuspended(
                actor_id=actor_id,
                reason=require_text(reason, field="suspension reason", maximum=240),
            )
        )

    def ensure_active(self) -> None:
        if self.suspended:
            raise AccessDeniedError("suspended members cannot perform this operation")

    def _apply(self, event: Event) -> None:
        match event:
            case MemberRegistered(
                handle=handle,
                display_name=display_name,
                visibility=visibility,
            ):
                self.handle = handle
                self.display_name = display_name
                self.visibility = visibility
            case DisplayNameChanged(display_name=display_name):
                self.display_name = display_name
            case MemberSuspended(reason=reason):
                self.suspended = True
                self.suspension_reason = reason
            case _:
                raise AssertionError(f"unknown member event: {event!r}")


__all__ = [
    "DisplayNameChanged",
    "Member",
    "MemberRegistered",
    "MemberSuspended",
]
