"""Shared values and dependency shapes for benchmark applications."""

from __future__ import annotations

from dataclasses import dataclass

HELLO_TEXT = "Hello, World!"
HELLO_BYTES = HELLO_TEXT.encode()
HEALTH_RESPONSE = {"status": "ok"}
JSON_RESPONSE = {"message": HELLO_TEXT}


@dataclass(frozen=True, slots=True)
class First:
    value: int = 5


@dataclass(frozen=True, slots=True)
class Second:
    first: First

    @property
    def value(self) -> int:
        return self.first.value


@dataclass(frozen=True, slots=True)
class Third:
    second: Second

    @property
    def value(self) -> int:
        return self.second.value


@dataclass(frozen=True, slots=True)
class Fourth:
    third: Third

    @property
    def value(self) -> int:
        return self.third.value


@dataclass(frozen=True, slots=True)
class Fifth:
    fourth: Fourth

    @property
    def value(self) -> int:
        return self.fourth.value


PREBUILT_DEPENDENCY = Fifth(Fourth(Third(Second(First()))))


def resolve_request_dependency() -> Fifth:
    """Construct the control application's dependency chain for one request."""
    return Fifth(Fourth(Third(Second(First()))))
