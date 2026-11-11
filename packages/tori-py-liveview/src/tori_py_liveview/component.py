from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from string.templatelib import Template
from typing import TYPE_CHECKING, Literal

from tori_py_liveview.errors import LiveViewError, UnknownAsyncError, UnknownEventError
from tori_py_liveview.rendering import Rendered, html

if TYPE_CHECKING:
    from tori_py_liveview.page import AsyncResult, LiveView


class LiveComponent(ABC):
    """A connection-local stateful component rendered by a LiveView."""

    _liveview_id: str | None = None
    _liveview_cid: int | None = None
    _liveview_connected = False
    _liveview_owner: LiveView | None = None

    def mount(self) -> None:
        return None

    def update(self, assigns: object) -> None:
        del assigns

    async def handle_event(
        self, event: str, value: object
    ) -> Mapping[str, object] | None:
        """Handle a targeted event; a returned mapping replies to the client."""
        del value
        raise UnknownEventError(event)

    def push_event(
        self,
        event: str,
        payload: Mapping[str, object] | None = None,
        *,
        dispatch: Literal["after", "before"] = "after",
    ) -> None:
        """Queue a browser event on the owning page; see ``LiveView.push_event``."""
        self._liveview_page().push_event(event, payload, dispatch=dispatch)

    def send_update(
        self,
        component_type: type[LiveComponent],
        component_id: str,
        assigns: object = None,
    ) -> None:
        """Queue a component update on the owning page."""
        self._liveview_page().send_update(component_type, component_id, assigns)

    def put_flash(self, kind: str, message: str) -> None:
        """Set a flash message on the owning page; see ``LiveView.put_flash``."""
        self._liveview_page().put_flash(kind, message)

    def clear_flash(self, kind: str | None = None) -> None:
        """Clear flash on the owning page; see ``LiveView.clear_flash``."""
        self._liveview_page().clear_flash(kind)

    def start_async(self, name: str, function: Callable[[], Awaitable[object]]) -> None:
        """Run async work owned by this component; see ``LiveView.start_async``."""
        page = self._liveview_page()
        page._start_liveview_async(self, name, function, assign=False)

    def assign_async(
        self,
        name: str,
        function: Callable[[], Awaitable[object]],
        *,
        reset: bool = False,
    ) -> None:
        """Track async work in a component attribute; see ``LiveView.assign_async``."""
        self._liveview_page()._assign_liveview_async(self, name, function, reset=reset)

    def cancel_async(self, name: str) -> bool:
        """Cancel this component's async work by name."""
        return self._liveview_page()._cancel_liveview_async(self, name)

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        """Handle the outcome of this component's ``start_async(name, ...)``."""
        del result
        raise UnknownAsyncError(name)

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

    def _attach_liveview(
        self,
        component_id: str,
        cid: int,
        connected: bool,
        owner: LiveView,
    ) -> None:
        if self._liveview_id is not None:
            raise LiveViewError("LiveView component is already attached")
        self._liveview_id = component_id
        self._liveview_cid = cid
        self._liveview_connected = connected
        self._liveview_owner = owner

    def _liveview_page(self) -> LiveView:
        if self._liveview_owner is None:
            raise LiveViewError("LiveView component is not attached")
        return self._liveview_owner

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
