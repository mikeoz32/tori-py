from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from tori_py_liveview.errors import LiveViewConfigurationError


@dataclass(frozen=True, slots=True)
class LiveSession:
    """A navigate boundary grouping live routes with shared mount hooks."""

    name: str
    on_mount: tuple[Callable[..., object], ...] = field(default=())

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise LiveViewConfigurationError("session name must be a non-empty string")
        try:
            hooks = tuple(self.on_mount)
        except TypeError as error:
            raise LiveViewConfigurationError(
                "session hooks must be iterable"
            ) from error
        for hook in hooks:
            if not callable(hook):
                raise LiveViewConfigurationError("session hooks must be callable")
        object.__setattr__(self, "on_mount", hooks)


def normalize_sessions(
    sessions: Iterable[LiveSession],
) -> dict[str, tuple[Callable[..., object], ...]]:
    try:
        declared = tuple(sessions)
    except TypeError as error:
        raise LiveViewConfigurationError("sessions must be iterable") from error
    normalized: dict[str, tuple[Callable[..., object], ...]] = {}
    for session in declared:
        if not isinstance(session, LiveSession):
            raise LiveViewConfigurationError("sessions must be LiveSession values")
        if session.name in normalized:
            raise LiveViewConfigurationError("session names must be unique")
        normalized[session.name] = session.on_mount
    return normalized


__all__ = ["LiveSession", "normalize_sessions"]
