from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from tori_py_liveview.errors import LiveViewConfigurationError


@dataclass(frozen=True, slots=True)
class LiveViewMetadata:
    path: str
    action: str | None = None
    session: str = ""


def live_view[T](
    path: str, *, action: str | None = None, session: str | None = None
) -> Callable[[type[T]], type[T]]:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or urlsplit(path).path != path
    ):
        raise LiveViewConfigurationError("live view path must be absolute")
    if action is not None and (not isinstance(action, str) or not action):
        raise LiveViewConfigurationError("live view action must be a non-empty string")
    if session is not None and (not isinstance(session, str) or not session):
        raise LiveViewConfigurationError("live view session must be a non-empty string")

    def decorate(page: type[T]) -> type[T]:
        existing = page.__dict__.get("__tori_py_liveview_routes__")
        if existing is None:
            routes: tuple[LiveViewMetadata, ...] = ()
        elif isinstance(existing, tuple):
            routes = existing
        else:
            raise LiveViewConfigurationError("live view path is already declared")
        if any(route.path == path for route in routes):
            raise LiveViewConfigurationError("live view path is already declared")
        declared = routes + (
            LiveViewMetadata(path, action, "" if session is None else session),
        )
        type.__setattr__(page, "__tori_py_liveview_routes__", declared)
        type.__setattr__(page, "__tori_py_liveview_metadata__", declared[0])
        return page

    return decorate


__all__ = ["LiveViewMetadata", "live_view"]
