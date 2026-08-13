"""Helpers for identifying message classes."""

from tori_py_cqrs_core.messages import Command, Event, Message, Query


def message_type_for(message_type: type[Message]) -> str:
    """Return the MVP routing identity for a message class."""

    if (
        not isinstance(message_type, type)
        or not issubclass(message_type, Message)
        or message_type in {Message, Command, Query, Event}
    ):
        raise TypeError("message_type must be a Message subclass")

    return f"{message_type.__module__}.{message_type.__qualname__}"
