from __future__ import annotations

from abc import ABC, abstractmethod
from string.templatelib import Template

from tori_py_liveview.errors import LiveViewError, UnknownEventError
from tori_py_liveview.rendering import Rendered, html


class LiveComponent(ABC):
    """A connection-local stateful component rendered by a LiveView."""

    _liveview_id: str | None = None
    _liveview_cid: int | None = None
    _liveview_connected = False

    def mount(self) -> None:
        return None

    def update(self, assigns: object) -> None:
        del assigns

    async def handle_event(self, event: str, value: object) -> None:
        del value
        raise UnknownEventError(event)

    async def disconnect(self) -> None:
        return None

    @abstractmethod
    def render(self) -> Rendered | Template | str: ...

    @property
    def id(self) -> str:
        if self._liveview_id is None:
            raise LiveViewError("LiveView component is not attached")
        return self._liveview_id

    @property
    def myself(self) -> int:
        if self._liveview_cid is None:
            raise LiveViewError("LiveView component is not attached")
        return self._liveview_cid

    @property
    def connected(self) -> bool:
        return self._liveview_connected

    def _attach_liveview(self, component_id: str, cid: int, connected: bool) -> None:
        if self._liveview_id is not None:
            raise LiveViewError("LiveView component is already attached")
        self._liveview_id = component_id
        self._liveview_cid = cid
        self._liveview_connected = connected

    def _render_liveview(self) -> Rendered:
        result = self.render()
        if isinstance(result, Rendered):
            return result
        if isinstance(result, Template):
            return html(result)
        if isinstance(result, str):
            return Rendered((result,), ())
        raise TypeError("LiveComponent.render must return Rendered, Template, or str")


__all__ = ["LiveComponent"]
