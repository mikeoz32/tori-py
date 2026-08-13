"""Message marker types used by the CQRS core."""


class Message:
    """Base type for every message accepted by the CQRS core."""

    __slots__ = ()


class Command[ResultT](Message):
    """A request that is handled exactly once and may return a result."""

    __slots__ = ()


class Query[ResultT](Message):
    """A read request that is handled exactly once and returns a result."""

    __slots__ = ()


class Event(Message):
    """A one-way notification that may have zero or more handlers."""

    __slots__ = ()
