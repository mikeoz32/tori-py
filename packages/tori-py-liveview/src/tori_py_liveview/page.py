from __future__ import annotations

import asyncio
import html
import inspect
import json
import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from string.templatelib import Template
from types import MappingProxyType
from typing import Literal, TypeVar, cast
from urllib.parse import urljoin, urlsplit

from starlette.datastructures import QueryParams

from tori_py_liveview.component import LiveComponent
from tori_py_liveview.errors import (
    LiveViewError,
    UnknownAsyncError,
    UnknownEventError,
    UnknownInfoError,
)
from tori_py_liveview.rendering import (
    Rendered,
    SafeHtml,
    _ComponentRendered,
    _StreamInsert,
    _StreamRendered,
    raw,
)
from tori_py_liveview.rendering import (
    html as render_template,
)
from tori_py_liveview.routing import redirect_target

_LOGGER = logging.getLogger(__name__)
_ComponentT = TypeVar("_ComponentT", bound=LiveComponent)
_ComponentIdentity = tuple[type[LiveComponent], str]
_MAX_SAFE_INTEGER = 2**53 - 1
_INFO_QUEUE_CAPACITY = 32
_ASYNC_CANCEL_TIMEOUT_SECONDS = 5.0
_VOID_ELEMENTS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)


class _UnknownComponentError(LiveViewError):
    pass


def _static_resource(url: str) -> str:
    try:
        split = urlsplit(urljoin("/", url))
    except ValueError:
        return url
    return f"{split.path}?{split.query}" if split.query else split.path


@dataclass(frozen=True, slots=True)
class MountContext:
    request: object
    params: Mapping[str, str]
    resource: str
    connected: bool
    query_params: QueryParams
    connect_params: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        if self.connect_params is not None:
            object.__setattr__(
                self, "connect_params", MappingProxyType(dict(self.connect_params))
            )

    @property
    def tracked_static(self) -> tuple[str, ...]:
        """URLs of the browser's ``phx-track-static`` elements at join."""
        params = self.connect_params
        tracked = None if params is None else params.get("_track_static")
        if not isinstance(tracked, list):
            return ()
        return tuple(url for url in cast(list[object], tracked) if isinstance(url, str))

    def static_changed(self, current: Iterable[str]) -> bool:
        """Whether a tracked static URL is missing from the ``current`` URLs.

        URLs compare by path and query, so a root-relative URL matches the
        absolute URL the browser reports. Like Phoenix ``static_changed?``, it
        is false for the disconnected mount and when the browser tracks nothing.
        """
        if isinstance(current, str):
            raise TypeError("current static URLs must be an iterable of strings")
        latest: set[str] = set()
        for url in current:
            if not isinstance(url, str):
                raise TypeError("current static URLs must be an iterable of strings")
            latest.add(_static_resource(url))
        return any(_static_resource(url) not in latest for url in self.tracked_static)


@dataclass(frozen=True, slots=True)
class AsyncResult[T]:
    """The state of async work, mirroring ``Phoenix.LiveView.AsyncResult``.

    ``ok`` stays true once a result arrived, so reloading keeps ``result``
    while ``loading`` is true. ``failed`` holds the latest failure, including
    ``asyncio.CancelledError`` after ``cancel_async``.
    """

    loading: bool = False
    ok: bool = False
    result: T | None = None
    failed: BaseException | None = None


@dataclass(eq=False, slots=True)
class _AsyncTask:
    owner: LiveView | LiveComponent
    name: str
    task: asyncio.Task[object]
    assign: bool


async def _run_async(function: Callable[[], object]) -> object:
    result = function()
    if not inspect.isawaitable(result):
        raise TypeError("LiveView async function must return an awaitable")
    return await result


@dataclass(frozen=True, slots=True)
class _StreamOperation:
    operation: str
    container_id: str
    item_id: str | None = None
    html: str | None = None
    at: int | None = None
    limit: int | None = None


class _FragmentRootParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.tags: list[str] = []
        self.roots = 0
        self.root_id: str | None = None
        self.invalid = False

    def _record_root(self, attrs: list[tuple[str, str | None]]) -> None:
        self.roots += 1
        root_ids = [value for name, value in attrs if name == "id"]
        if len(root_ids) > 1:
            self.invalid = True
        self.root_id = root_ids[0] if root_ids else None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.depth == 0:
            self._record_root(attrs)
        if tag not in _VOID_ELEMENTS:
            self.tags.append(tag)
            self.depth += 1

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.depth == 0:
            self._record_root(attrs)
        if tag not in _VOID_ELEMENTS:
            self.invalid = True

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID_ELEMENTS:
            return
        if self.depth == 0:
            self.invalid = True
            return
        if self.tags.pop() != tag:
            self.invalid = True
        self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth == 0 and data.strip():
            self.invalid = True

    def handle_decl(self, decl: str) -> None:
        del decl
        if self.depth == 0:
            self.invalid = True


def _fragment_root(value: str) -> tuple[bool, str | None]:
    parser = _FragmentRootParser()
    parser.feed(value)
    parser.close()
    if parser.invalid or parser.depth != 0 or parser.roots != 1:
        return False, None
    return True, parser.root_id


def _json_object(name: str, value: object) -> dict[str, object]:
    """Snapshot a mapping as the JSON object the Phoenix client receives."""
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise TypeError(f"{name} keys must be strings")
    try:
        encoded = json.dumps(dict(mapping), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError(f"{name} must encode as a JSON object") from error
    return cast(dict[str, object], json.loads(encoded))


@dataclass(frozen=True, slots=True)
class _Info:
    name: str
    value: object


class LiveView(ABC):
    _liveview_action: str | None = None
    _liveview_pending_redirect: tuple[str, str, str] | None = None

    async def mount(self, context: MountContext) -> None:
        del context

    async def handle_params(self, params: dict[str, str], uri: str) -> None:
        del params, uri

    @property
    def live_action(self) -> str | None:
        return self._liveview_action

    async def handle_event(
        self, event: str, value: object
    ) -> Mapping[str, object] | None:
        """Handle a browser event; a returned mapping replies to the client."""
        del value
        raise UnknownEventError(event)

    async def handle_info(self, name: str, value: object) -> None:
        del value
        raise UnknownInfoError(name)

    async def handle_async(self, name: str, result: AsyncResult[object]) -> None:
        """Handle the outcome of ``start_async(name, ...)``."""
        del result
        raise UnknownAsyncError(name)

    async def disconnect(self) -> None:
        return None

    @abstractmethod
    def render(self) -> Rendered | Template | str: ...

    def title(self) -> str | None:
        return None

    def render_document(self, live_root: str, client_script: str) -> str:
        title = self.title()
        title_html = (
            '<title data-default="">'
            f"{'' if title is None else html.escape(title, quote=True)}</title>"
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
            component = self._liveview_pending_components.pop(identity, None)
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
                    self,
                )
                component.mount()
            else:
                self._liveview_pending_components_by_cid.pop(component.myself, None)
                self._liveview_destroy_candidates.discard(component.myself)
            components[identity] = component
            self._liveview_components_by_cid[component.myself] = component

        rendered_components.add(identity)
        component.update(assigns)
        component_rendered = component._render_liveview()
        if not _fragment_root(component_rendered.to_html())[0]:
            raise LiveViewError(
                "LiveView components require exactly one explicitly balanced "
                "root element"
            )
        return _ComponentRendered(
            component_rendered.statics,
            component_rendered.dynamics,
            component.myself,
        )

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
        valid_root, root_id = _fragment_root(item_html)
        if not valid_root or root_id != item_id:
            raise ValueError(
                "LiveView stream items require one explicitly balanced root element "
                "with the declared id"
            )

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
        operations = [
            operation
            for operation in self._liveview_stream_operations
            if operation.container_id == container_id
        ]
        if getattr(self, "_liveview_connected", False):
            return self._connected_stream_contents(container_id, operations)

        items: list[tuple[str, str]] = []

        for operation in operations:
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

    @staticmethod
    def _connected_stream_contents(
        container_id: str,
        operations: list[_StreamOperation],
    ) -> _StreamRendered:
        inserts: dict[str, _StreamInsert] = {}
        delete_ids: list[str] = []
        reset = False
        for operation in operations:
            if operation.operation == "reset":
                inserts.clear()
                delete_ids.clear()
                reset = True
                continue
            assert operation.item_id is not None
            if operation.operation == "delete":
                inserts.pop(operation.item_id, None)
                if operation.item_id not in delete_ids:
                    delete_ids.append(operation.item_id)
                continue
            assert operation.html is not None
            assert operation.at is not None
            if operation.item_id in delete_ids:
                delete_ids.remove(operation.item_id)
            inserts[operation.item_id] = _StreamInsert(
                operation.item_id,
                operation.html,
                operation.at,
                operation.limit,
            )
        return _StreamRendered(
            "".join(item.html for item in inserts.values()),
            container_id,
            tuple(inserts.values()),
            tuple(delete_ids),
            reset,
        )

    def send_info(self, name: str, value: object = None) -> bool:
        queue = getattr(self, "_liveview_info_queue", None)
        if queue is None or self._liveview_info_pending >= _INFO_QUEUE_CAPACITY:
            return False
        self._liveview_info_pending += 1
        queue.put_nowait(_Info(name, value))
        return True

    @property
    def flash(self) -> Mapping[str, str]:
        """Current flash messages by kind, for ``render`` to display."""
        self._initialize_liveview_flash()
        return MappingProxyType(self._liveview_flash)

    def put_flash(self, kind: str, message: str) -> None:
        """Set a flash message; it follows ``push_navigate`` and ``redirect``."""
        if not isinstance(kind, str) or not isinstance(message, str):
            raise TypeError("LiveView flash kind and message must be strings")
        if not kind:
            raise ValueError("LiveView flash kind cannot be empty")
        self._initialize_liveview_flash()
        self._liveview_flash[kind] = message
        self._liveview_flash_changes[kind] = message

    def clear_flash(self, kind: str | None = None) -> None:
        """Remove one flash kind, or every flash message when ``kind`` is None."""
        if kind is not None and not isinstance(kind, str):
            raise TypeError("LiveView flash kind must be a string")
        self._initialize_liveview_flash()
        if kind is None:
            self._liveview_flash.clear()
            self._liveview_flash_changes.clear()
            return
        self._liveview_flash.pop(kind, None)
        self._liveview_flash_changes.pop(kind, None)

    def start_async(self, name: str, function: Callable[[], Awaitable[object]]) -> None:
        """Await ``function()`` concurrently and pass its result to ``handle_async``.

        Only a connected page starts work; the disconnected render ignores the
        call. Starting a name that is still running cancels the previous task
        and drops its result. Disconnect cancels every task.
        """
        self._start_liveview_async(self, name, function, assign=False)

    def assign_async(
        self,
        name: str,
        function: Callable[[], Awaitable[object]],
        *,
        reset: bool = False,
    ) -> None:
        """Track ``function()`` in the ``AsyncResult`` attribute ``name``.

        The attribute becomes loading now, keeping a previous result unless
        ``reset`` is true, and settles to ok or failed when the work finishes.
        """
        self._assign_liveview_async(self, name, function, reset=reset)

    def cancel_async(self, name: str) -> bool:
        """Cancel async work by name; its outcome arrives as a cancellation."""
        return self._cancel_liveview_async(self, name)

    def push_event(
        self,
        event: str,
        payload: Mapping[str, object] | None = None,
        *,
        dispatch: Literal["after", "before"] = "after",
    ) -> None:
        """Send a ``phx:<event>`` browser event with the next render.

        ``dispatch="before"`` dispatches it before the client applies the diff.
        """
        if not isinstance(event, str):
            raise TypeError("LiveView pushed event name must be a string")
        if not event:
            raise ValueError("LiveView pushed event name cannot be empty")
        if dispatch not in ("after", "before"):
            raise ValueError("LiveView push_event dispatch must be 'after' or 'before'")
        entry: list[object] = [
            event,
            _json_object(
                "LiveView pushed event payload", {} if payload is None else payload
            ),
        ]
        if dispatch == "before":
            entry.append(True)
        self._initialize_liveview_handler_queues()
        self._liveview_pushed_events.append(entry)

    def send_update(
        self,
        component_type: type[LiveComponent],
        component_id: str,
        assigns: object = None,
    ) -> None:
        """Call ``update(assigns)`` on a rendered component before the next render."""
        if not isinstance(component_type, type) or not issubclass(
            component_type,
            LiveComponent,
        ):
            raise TypeError("component_type must be a LiveComponent subclass")
        if not isinstance(component_id, str):
            raise TypeError("LiveView component id must be a string")
        self._initialize_liveview_handler_queues()
        self._liveview_component_updates.append(
            ((component_type, component_id), assigns)
        )

    def push_patch(self, to: str, *, kind: str = "push") -> None:
        """Navigate within the current page; applied after the handler renders."""
        if not isinstance(to, str) or not to:
            raise LiveViewError("push_patch target must be a non-empty string")
        if kind not in {"push", "replace"}:
            raise LiveViewError("push_patch kind must be 'push' or 'replace'")
        self._liveview_pending_redirect = ("patch", to, kind)

    def push_navigate(self, to: str, *, kind: str = "push") -> None:
        """Navigate to another page in the session; otherwise full reload."""
        if not isinstance(to, str) or not to:
            raise LiveViewError("push_navigate target must be a non-empty string")
        if kind not in {"push", "replace"}:
            raise LiveViewError("push_navigate kind must be 'push' or 'replace'")
        self._liveview_pending_redirect = ("navigate", to, kind)

    def redirect(self, to: str) -> None:
        """Navigate with a full page reload; applied after the handler renders.

        The target is cleaned and must be a path or an http(s) URL on the
        request host or on a host listed in ``LiveViewOptions.redirect_hosts``.
        """
        if not isinstance(to, str) or not to:
            raise LiveViewError("redirect target must be a non-empty string")
        self._liveview_pending_redirect = ("redirect", redirect_target(to), "push")

    def _take_liveview_pending_redirect(self) -> tuple[str, str, str] | None:
        pending = self._liveview_pending_redirect
        self._liveview_pending_redirect = None
        return pending

    def _take_liveview_events(self) -> list[list[object]]:
        self._initialize_liveview_handler_queues()
        events = self._liveview_pushed_events
        self._liveview_pushed_events = []
        return events

    def _discard_liveview_effects(self) -> None:
        """Drop everything a rejected handler queued for the next render."""
        self._liveview_pending_redirect = None
        self._clear_liveview_stream_operations()
        self._clear_liveview_handler_queues()
        self._take_liveview_flash_changes()

    def _set_liveview_flash(self, flash: Mapping[str, str]) -> None:
        self._initialize_liveview_flash()
        self._liveview_flash = dict(flash)
        self._liveview_flash_changes = {}

    def _take_liveview_flash_changes(self) -> dict[str, str]:
        """Return and forget the flash put since the last render or navigation."""
        self._initialize_liveview_flash()
        changes = self._liveview_flash_changes
        self._liveview_flash_changes = {}
        return changes

    def _initialize_liveview_flash(self) -> None:
        if hasattr(self, "_liveview_flash"):
            return
        self._liveview_flash: dict[str, str] = {}
        self._liveview_flash_changes: dict[str, str] = {}

    def _start_liveview_async(
        self,
        owner: LiveView | LiveComponent,
        name: str,
        function: Callable[[], Awaitable[object]],
        *,
        assign: bool,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError("LiveView async name must be a string")
        if not name:
            raise ValueError("LiveView async name cannot be empty")
        if not callable(function):
            raise TypeError("LiveView async function must be callable")
        if getattr(self, "_liveview_info_queue", None) is None:
            return
        self._initialize_liveview_async()
        previous = self._liveview_async.pop((id(owner), name), None)
        if previous is not None:
            previous.task.cancel()
        task = asyncio.get_running_loop().create_task(
            _run_async(function), name=f"tori-py-liveview async {name}"
        )
        entry = _AsyncTask(owner, name, task, assign)
        self._liveview_async[(id(owner), name)] = entry
        self._liveview_async_running.add(task)
        task.add_done_callback(lambda _: self._complete_liveview_async(entry))

    def _assign_liveview_async(
        self,
        owner: LiveView | LiveComponent,
        name: str,
        function: Callable[[], Awaitable[object]],
        *,
        reset: bool,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError("LiveView async name must be a string")
        if not name.isidentifier() or name.startswith("_"):
            raise ValueError("LiveView assign_async name must be a public attribute")
        if not callable(function):
            raise TypeError("LiveView async function must be callable")
        current = getattr(owner, name, None)
        previous = (
            current if isinstance(current, AsyncResult) and not reset else AsyncResult()
        )
        setattr(owner, name, replace(previous, loading=True, failed=None))
        self._start_liveview_async(owner, name, function, assign=True)

    def _cancel_liveview_async(
        self, owner: LiveView | LiveComponent, name: str
    ) -> bool:
        if not isinstance(name, str):
            raise TypeError("LiveView async name must be a string")
        self._initialize_liveview_async()
        entry = self._liveview_async.get((id(owner), name))
        if entry is None:
            return False
        entry.task.cancel()
        return True

    def _complete_liveview_async(self, entry: _AsyncTask) -> None:
        self._liveview_async_running.discard(entry.task)
        if not entry.task.cancelled():
            entry.task.exception()
        queue = getattr(self, "_liveview_info_queue", None)
        current = self._liveview_async.get((id(entry.owner), entry.name))
        if queue is not None and current is entry:
            queue.put_nowait(entry)

    async def _settle_liveview_async(self, entry: _AsyncTask) -> bool:
        """Deliver a finished task unless it was replaced; True when delivered."""
        self._initialize_liveview_async()
        key = (id(entry.owner), entry.name)
        if self._liveview_async.get(key) is not entry:
            return False
        del self._liveview_async[key]
        task = entry.task
        if task.cancelled():
            outcome = AsyncResult[object](failed=asyncio.CancelledError())
        elif (error := task.exception()) is not None:
            _LOGGER.warning(
                "LiveView async task failed: owner=%s name=%s",
                type(entry.owner).__qualname__,
                entry.name,
                exc_info=error,
            )
            outcome = AsyncResult[object](failed=error)
        else:
            outcome = AsyncResult[object](ok=True, result=task.result())
        if not entry.assign:
            await entry.owner.handle_async(entry.name, outcome)
            return True
        current = getattr(entry.owner, entry.name, None)
        state = current if isinstance(current, AsyncResult) else AsyncResult()
        if outcome.ok:
            state = replace(
                state, loading=False, ok=True, result=outcome.result, failed=None
            )
        else:
            state = replace(state, loading=False, failed=outcome.failed)
        setattr(entry.owner, entry.name, state)
        return True

    async def _stop_liveview_owner_async(self, owner: LiveView | LiveComponent) -> None:
        """Cancel one owner's work and wait for it within the cancel deadline."""
        self._initialize_liveview_async()
        registry = self._liveview_async
        owned = [key for key, entry in registry.items() if entry.owner is owner]
        tasks = [registry.pop(key).task for key in owned]
        for task in tasks:
            task.cancel()
        await self._await_cancelled_liveview_async(tasks)

    async def _stop_liveview_async(self) -> None:
        self._initialize_liveview_async()
        self._liveview_async.clear()
        running = list(self._liveview_async_running)
        for task in running:
            task.cancel()
        await self._await_cancelled_liveview_async(running)

    async def _await_cancelled_liveview_async(
        self, tasks: list[asyncio.Task[object]]
    ) -> None:
        # Python cancellation is cooperative, so a task that suppresses it would
        # block disconnect, navigation, and shutdown without a deadline.
        pending = [task for task in tasks if not task.done()]
        if not pending:
            return
        timeout = getattr(
            self, "_liveview_async_cancel_timeout", _ASYNC_CANCEL_TIMEOUT_SECONDS
        )
        _, stuck = await asyncio.wait(pending, timeout=timeout)
        if stuck:
            _LOGGER.warning(
                "LiveView async work ignored cancellation for %ss: %s",
                timeout,
                ", ".join(sorted(task.get_name() for task in stuck)),
            )

    def _initialize_liveview_async(self) -> None:
        if hasattr(self, "_liveview_async"):
            return
        self._liveview_async: dict[tuple[int, str], _AsyncTask] = {}
        self._liveview_async_running: set[asyncio.Task[object]] = set()

    def _clear_liveview_handler_queues(self) -> None:
        self._initialize_liveview_handler_queues()
        self._liveview_pushed_events.clear()
        self._liveview_component_updates.clear()

    def _initialize_liveview_handler_queues(self) -> None:
        if hasattr(self, "_liveview_pushed_events"):
            return
        self._liveview_pushed_events: list[list[object]] = []
        self._liveview_component_updates: list[tuple[_ComponentIdentity, object]] = []

    def _connect_liveview(
        self, *, async_cancel_timeout: float = _ASYNC_CANCEL_TIMEOUT_SECONDS
    ) -> None:
        # send_info is bounded by a pending count; each async task enqueues at
        # most one completion, so the shared queue itself is unbounded.
        self._liveview_info_queue: asyncio.Queue[_Info | _AsyncTask] | None = (
            asyncio.Queue()
        )
        self._liveview_info_pending = 0
        self._liveview_async_cancel_timeout = async_cancel_timeout

    async def _receive_liveview_info(self) -> _Info | _AsyncTask:
        queue = getattr(self, "_liveview_info_queue", None)
        if queue is None:
            raise LiveViewError("LiveView is not connected")
        message = await queue.get()
        if isinstance(message, _Info):
            self._liveview_info_pending -= 1
        return message

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

        self._initialize_liveview_handler_queues()
        updates = self._liveview_component_updates
        self._liveview_component_updates = []
        for identity, assigns in updates:
            component = self._liveview_components.get(identity)
            if component is not None:
                component.update(assigns)

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
            self._liveview_pending_components[identity] = component
            self._liveview_pending_components_by_cid[component.myself] = (
                identity,
                component,
            )
        return rendered

    async def _handle_liveview_event(
        self,
        target: int | None,
        event: str,
        value: object,
    ) -> Mapping[str, object] | None:
        component: LiveComponent | None = None
        if target is not None:
            self._initialize_liveview_components()
            component = self._liveview_components_by_cid.get(target)
            if component is None:
                raise _UnknownComponentError("Unknown LiveView component target")
        if event == "lv:clear-flash":
            # Phoenix's built-in flash dismissal, for pages and components alike.
            key = value.get("key") if isinstance(value, Mapping) else None
            self.clear_flash(key if isinstance(key, str) else None)
            return None
        if component is None:
            return await self.handle_event(event, value)
        return await component.handle_event(event, value)

    async def _disconnect_liveview_components(self) -> None:
        self._initialize_liveview_components()
        self._clear_liveview_stream_operations()
        self._clear_liveview_handler_queues()
        components = [
            *self._liveview_components.values(),
            *self._liveview_pending_components.values(),
        ]
        self._liveview_components.clear()
        self._liveview_components_by_cid.clear()
        self._liveview_pending_components.clear()
        self._liveview_pending_components_by_cid.clear()
        self._liveview_destroy_candidates.clear()
        self._liveview_rendered_components = None
        for component in components:
            await self._disconnect_liveview_component(component)

    def _prepare_liveview_component_destruction(self, cids: list[int]) -> None:
        self._initialize_liveview_components()
        self._liveview_destroy_candidates.update(
            cid for cid in cids if cid in self._liveview_pending_components_by_cid
        )

    async def _destroy_liveview_components(self, cids: list[int]) -> list[int]:
        self._initialize_liveview_components()
        destroyed: list[int] = []
        for cid in cids:
            if cid not in self._liveview_destroy_candidates:
                continue
            pending = self._liveview_pending_components_by_cid.pop(cid, None)
            self._liveview_destroy_candidates.discard(cid)
            if pending is None:
                continue
            identity, component = pending
            if self._liveview_pending_components.pop(identity, None) is not component:
                continue
            await self._disconnect_liveview_component(component)
            destroyed.append(cid)
        return destroyed

    async def _disconnect_liveview(self) -> None:
        self._detach_liveview()
        await self._stop_liveview_async()
        await self._disconnect_liveview_components()
        await self.disconnect()

    def _initialize_liveview_components(self) -> None:
        if hasattr(self, "_liveview_components"):
            return
        self._liveview_components: dict[_ComponentIdentity, LiveComponent] = {}
        self._liveview_components_by_cid: dict[int, LiveComponent] = {}
        self._liveview_pending_components: dict[_ComponentIdentity, LiveComponent] = {}
        self._liveview_pending_components_by_cid: dict[
            int, tuple[_ComponentIdentity, LiveComponent]
        ] = {}
        self._liveview_destroy_candidates: set[int] = set()
        self._liveview_rendered_components: set[_ComponentIdentity] | None = None
        self._liveview_next_component_cid = 0
        self._liveview_connected = False

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
        if any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value):
            raise ValueError(
                f"LiveView stream {kind} id cannot contain ASCII whitespace or "
                "control characters"
            )

    async def _disconnect_liveview_component(self, component: LiveComponent) -> None:
        # Stop the component's work before its own disconnect hook runs.
        await self._stop_liveview_owner_async(component)
        try:
            await component.disconnect()
        except Exception:
            _LOGGER.exception(
                "LiveView component cleanup failed: component=%s",
                type(component).__qualname__,
            )


__all__ = [
    "AsyncResult",
    "LiveView",
    "MountContext",
    "_AsyncTask",
    "_UnknownComponentError",
    "_json_object",
]
