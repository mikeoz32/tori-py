from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from tori_py_liveview.errors import LiveViewConfigurationError


@dataclass(frozen=True, slots=True)
class LiveViewMetadata:
    path: str


def live_view[T](path: str) -> Callable[[type[T]], type[T]]:
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path.startswith("//")
        or urlsplit(path).path != path
    ):
        raise LiveViewConfigurationError("live view path must be absolute")

    def decorate(page: type[T]) -> type[T]:
        if "__tori_py_liveview_metadata__" in page.__dict__:
            raise LiveViewConfigurationError("live view path is already declared")
        type.__setattr__(page, "__tori_py_liveview_metadata__", LiveViewMetadata(path))
        return page

    return decorate


__all__ = ["LiveViewMetadata", "live_view"]
