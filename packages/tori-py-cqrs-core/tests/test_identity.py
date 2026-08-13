from dataclasses import dataclass
from typing import cast

import pytest
from tori_py_cqrs_core import Command, Message, message_type_for


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


class NotAMessage:
    pass


def test_message_type_uses_fully_qualified_class_path() -> None:
    assert message_type_for(CreateProfile) == f"{__name__}.CreateProfile"


def test_message_type_rejects_non_message_classes() -> None:
    with pytest.raises(TypeError, match="Message subclass"):
        message_type_for(cast(type[Message], NotAMessage))


def test_message_base_is_not_a_concrete_routing_message() -> None:
    with pytest.raises(TypeError, match="Message subclass"):
        message_type_for(Message)  # type: ignore[arg-type]
