from __future__ import annotations

import html
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TypeVar, cast

from starlette.datastructures import QueryParams

from tori_py_liveview.component import LiveComponent
from tori_py_liveview.errors import LiveViewError, UnknownEventError
from tori_py_liveview.rendering import Rendered

_LOGGER = logging.getLogger(__name__)
_ComponentT = TypeVar("_ComponentT", bound=LiveComponent)
_ComponentIdentity = tuple[type[LiveComponent], str]


class _UnknownComponentError(LiveViewError):
    pass


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

    def live_component(
        self,
        component_type: type[_ComponentT],
        component_id: str,
        assigns: object = None,
        *,
        factory: Callable[[], _ComponentT] | None = None,
    ) -> Rendered:
        rendered_components = getattr(
            self,
            "_liveview_rendered_components",
            None,
        )
        if rendered_components is None:
            raise LiveViewError(
                "LiveView components can only be rendered from LiveView.render"
            )
        if not isinstance(component_id, str):
            raise TypeError("LiveView component id must be a string")
        if not isinstance(component_type, type) or not issubclass(
            component_type,
            LiveComponent,
        ):
            raise TypeError("component_type must be a LiveComponent subclass")

        identity = (cast(type[LiveComponent], component_type), component_id)
        if identity in rendered_components:
            raise LiveViewError(
                f"Duplicate LiveView component identity for {component_type.__name__}"
            )

        self._initialize_liveview_components()
        components = self._liveview_components
        component = components.get(identity)
        if component is None:
            component = component_type() if factory is None else factory()
            if type(component) is not component_type:
                raise TypeError(
                    "component factory must return the declared component type"
                )
            self._liveview_next_component_cid += 1
            component._attach_liveview(
                component_id,
                self._liveview_next_component_cid,
                self._liveview_connected,
            )
            components[identity] = component
            self._liveview_components_by_cid[component.myself] = component
            component.mount()

        rendered_components.add(identity)
        component.update(assigns)
        return component._render_liveview()

    async def _mount_liveview(self, context: MountContext) -> None:
        self._initialize_liveview_components()
        self._liveview_connected = context.connected
        await self.mount(context)

    async def _render_liveview(self) -> Rendered:
        self._initialize_liveview_components()
        if self._liveview_rendered_components is not None:
            raise LiveViewError("LiveView render is already in progress")

        rendered_components: set[_ComponentIdentity] = set()
        self._liveview_rendered_components = rendered_components
        try:
            result = self.render()
            if isinstance(result, Rendered):
                rendered = result
            elif isinstance(result, str):
                rendered = Rendered((result,), ())
            else:
                raise TypeError("LiveView.render must return Rendered or str")
        finally:
            self._liveview_rendered_components = None

        stale = [
            identity
            for identity in self._liveview_components
            if identity not in rendered_components
        ]
        for identity in stale:
            component = self._liveview_components.pop(identity)
            self._liveview_components_by_cid.pop(component.myself, None)
            await self._disconnect_liveview_component(component)
        return rendered

    async def _handle_liveview_event(
        self,
        target: int | None,
        event: str,
        value: object,
    ) -> None:
        if target is None:
            await self.handle_event(event, value)
            return
        self._initialize_liveview_components()
        component = self._liveview_components_by_cid.get(target)
        if component is None:
            raise _UnknownComponentError("Unknown LiveView component target")
        await component.handle_event(event, value)

    async def _disconnect_liveview_components(self) -> None:
        self._initialize_liveview_components()
        components = list(self._liveview_components.values())
        self._liveview_components.clear()
        self._liveview_components_by_cid.clear()
        self._liveview_rendered_components = None
        for component in components:
            await self._disconnect_liveview_component(component)

    async def _disconnect_liveview(self) -> None:
        await self._disconnect_liveview_components()
        await self.disconnect()

    def _initialize_liveview_components(self) -> None:
        if hasattr(self, "_liveview_components"):
            return
        self._liveview_components: dict[_ComponentIdentity, LiveComponent] = {}
        self._liveview_components_by_cid: dict[int, LiveComponent] = {}
        self._liveview_rendered_components: set[_ComponentIdentity] | None = None
        self._liveview_next_component_cid = 0
        self._liveview_connected = False

    async def _disconnect_liveview_component(self, component: LiveComponent) -> None:
        try:
            await component.disconnect()
        except Exception:
            _LOGGER.exception(
                "LiveView component cleanup failed: component=%s",
                type(component).__qualname__,
            )


__all__ = ["LiveView", "MountContext", "_UnknownComponentError"]
