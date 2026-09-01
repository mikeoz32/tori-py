from __future__ import annotations

import html
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from starlette.datastructures import QueryParams

from tori_py_liveview.errors import UnknownEventError
from tori_py_liveview.rendering import Rendered


@dataclass(frozen=True, slots=True)
class MountContext:
    request: object
    params: Mapping[str, str]
    resource: str
    connected: bool
    query_params: QueryParams

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


class LiveView(ABC):
    async def mount(self, context: MountContext) -> None:
        del context

    async def handle_event(self, event: str, value: object) -> None:
        del value
        raise UnknownEventError(event)

    async def disconnect(self) -> None:
        return None

    @abstractmethod
    def render(self) -> Rendered | str: ...

    def title(self) -> str | None:
        return None

    def render_document(self, live_root: str, client_script: str) -> str:
        title = self.title()
        title_html = (
            "" if title is None else f"<title>{html.escape(title, quote=True)}</title>"
        )
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"{title_html}</head><body>{live_root}{client_script}</body></html>"
        )


__all__ = ["LiveView", "MountContext"]
