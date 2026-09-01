from __future__ import annotations

import asyncio
import html
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from string.templatelib import Template
from types import MappingProxyType
from typing import TypeVar, cast

from starlette.datastructures import QueryParams

from tori_py_liveview.component import LiveComponent
from tori_py_liveview.errors import LiveViewError, UnknownEventError, UnknownInfoError
from tori_py_liveview.rendering import Rendered, SafeHtml, raw
from tori_py_liveview.rendering import html as render_template

_LOGGER = logging.getLogger(__name__)
_ComponentT = TypeVar("_ComponentT", bound=LiveComponent)
_ComponentIdentity = tuple[type[LiveComponent], str]
_MAX_SAFE_INTEGER = 2**53 - 1
_INFO_QUEUE_CAPACITY = 32


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


@dataclass(frozen=True, slots=True)
class _StreamOperation:
    operation: str
    container_id: str
    item_id: str | None = None
    html: str | None = None
    at: int | None = None
    limit: int | None = None

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "op": self.operation,
            "container": self.container_id,
        }
        if self.item_id is not None:
            result["id"] = self.item_id
        if self.html is not None:
            result["html"] = self.html
        if self.at is not None:
            result["at"] = self.at
        if self.limit is not None:
            result["limit"] = self.limit
        return result


@dataclass(frozen=True, slots=True)
class _Info:
    name: str
    value: object


class LiveView(ABC):
    async def mount(self, context: MountContext) -> None:
        del context

    async def handle_event(self, event: str, value: object) -> None:
        del value
        raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        del value
        raise UnknownInfoError(name)

    async def disconnect(self) -> None:
        return None

    @abstractmethod
    def render(self) -> Rendered | Template | str: ...

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

    def stream_insert(
        self,
        container_id: str,
        item_id: str,
        item: Rendered | Template | str,
        *,
        at: int = -1,
        limit: int | None = None,
    ) -> None:
        self._validate_stream_id(container_id, "container")
        self._validate_stream_id(item_id, "item")
        if type(at) is not int:
            raise TypeError("LiveView stream insertion index must be an integer")
        if at < -1:
            raise ValueError("LiveView stream insertion index must be -1 or greater")
        if at > _MAX_SAFE_INTEGER:
            raise ValueError("LiveView stream insertion index must be a safe integer")
        if limit is not None:
            if type(limit) is not int:
                raise TypeError("LiveView stream limit must be an integer or None")
            if limit == 0:
                raise ValueError("LiveView stream limit cannot be zero")
            if abs(limit) > _MAX_SAFE_INTEGER:
                raise ValueError("LiveView stream limit must be a safe integer")

        if isinstance(item, Rendered):
            item_html = item.to_html()
        elif isinstance(item, Template):
            item_html = render_template(item).to_html()
        elif isinstance(item, str):
            item_html = item
        else:
            raise TypeError("LiveView stream item must be Rendered, Template, or str")

        self._initialize_liveview_streams()
        self._liveview_stream_operations.append(
            _StreamOperation(
                "insert",
                container_id,
                item_id=item_id,
                html=item_html,
                at=at,
                limit=limit,
            )
        )

    def stream_delete(self, container_id: str, item_id: str) -> None:
        self._validate_stream_id(container_id, "container")
        self._validate_stream_id(item_id, "item")
        self._initialize_liveview_streams()
        self._liveview_stream_operations.append(
            _StreamOperation("delete", container_id, item_id=item_id)
        )

    def stream_reset(self, container_id: str) -> None:
        self._validate_stream_id(container_id, "container")
        self._initialize_liveview_streams()
        self._liveview_stream_operations.append(_StreamOperation("reset", container_id))

    def stream_contents(self, container_id: str) -> SafeHtml:
        self._validate_stream_id(container_id, "container")
        self._initialize_liveview_streams()
        items: list[tuple[str, str]] = []

        for operation in self._liveview_stream_operations:
            if operation.container_id != container_id:
                continue
            if operation.operation == "reset":
                items.clear()
            elif operation.operation == "delete":
                items = [item for item in items if item[0] != operation.item_id]
            else:
                assert operation.item_id is not None
                assert operation.html is not None
                existing = next(
                    (
                        index
                        for index, item in enumerate(items)
                        if item[0] == operation.item_id
                    ),
                    None,
                )
                if existing is not None:
                    items[existing] = (operation.item_id, operation.html)
                else:
                    assert operation.at is not None
                    index = (
                        len(items)
                        if operation.at == -1 or operation.at >= len(items)
                        else operation.at
                    )
                    items.insert(index, (operation.item_id, operation.html))
                if operation.limit is not None:
                    if operation.limit > 0:
                        del items[operation.limit :]
                    else:
                        del items[: max(0, len(items) + operation.limit)]

        return raw("".join(item[1] for item in items))

    def send_info(self, name: str, value: object = None) -> bool:
        queue = getattr(self, "_liveview_info_queue", None)
        if queue is None:
            return False
        try:
            queue.put_nowait(_Info(name, value))
        except asyncio.QueueFull:
            return False
        return True

    def _connect_liveview(self) -> None:
        self._liveview_info_queue: asyncio.Queue[_Info] | None = asyncio.Queue(
            maxsize=_INFO_QUEUE_CAPACITY
        )

    async def _receive_liveview_info(self) -> _Info:
        queue = getattr(self, "_liveview_info_queue", None)
        if queue is None:
            raise LiveViewError("LiveView is not connected")
        return await queue.get()

    def _detach_liveview(self) -> None:
        self._liveview_info_queue = None

    async def _mount_liveview(self, context: MountContext) -> None:
        self._initialize_liveview_components()
        self._initialize_liveview_streams()
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
            elif isinstance(result, Template):
                rendered = render_template(result)
            elif isinstance(result, str):
                rendered = Rendered((result,), ())
            else:
                raise TypeError(
                    "LiveView.render must return Rendered, Template, or str"
                )
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
        self._clear_liveview_stream_operations()
        components = list(self._liveview_components.values())
        self._liveview_components.clear()
        self._liveview_components_by_cid.clear()
        self._liveview_rendered_components = None
        for component in components:
            await self._disconnect_liveview_component(component)

    async def _disconnect_liveview(self) -> None:
        self._detach_liveview()
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

    def _take_liveview_stream_operations(self) -> list[dict[str, object]]:
        self._initialize_liveview_streams()
        operations = self._liveview_stream_operations
        self._liveview_stream_operations = []
        return [operation.payload() for operation in operations]

    def _clear_liveview_stream_operations(self) -> None:
        self._initialize_liveview_streams()
        self._liveview_stream_operations.clear()

    def _initialize_liveview_streams(self) -> None:
        if hasattr(self, "_liveview_stream_operations"):
            return
        self._liveview_stream_operations: list[_StreamOperation] = []

    @staticmethod
    def _validate_stream_id(value: object, kind: str) -> None:
        if not isinstance(value, str):
            raise TypeError(f"LiveView stream {kind} id must be a string")
        if not value:
            raise ValueError(f"LiveView stream {kind} id cannot be empty")

    async def _disconnect_liveview_component(self, component: LiveComponent) -> None:
        try:
            await component.disconnect()
        except Exception:
            _LOGGER.exception(
                "LiveView component cleanup failed: component=%s",
                type(component).__qualname__,
            )


__all__ = ["LiveView", "MountContext", "_UnknownComponentError"]
