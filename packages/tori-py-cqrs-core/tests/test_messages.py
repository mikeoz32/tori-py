from dataclasses import FrozenInstanceError, dataclass

import pytest
from tori_py_cqrs_core import Command, Event, Query


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[str]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int


def test_messages_are_typed_marker_subclasses() -> None:
    command = CreateProfile(username="alice")
    query = GetProfile(profile_id=1)
    event = ProfileCreated(profile_id=1)

    assert isinstance(command, Command)
    assert isinstance(query, Query)
    assert isinstance(event, Event)
    assert not hasattr(command, "__dict__")


def test_frozen_message_cannot_be_mutated() -> None:
    command = CreateProfile(username="alice")

    with pytest.raises(FrozenInstanceError):
        type(command).__setattr__(command, "username", "bob")
