"""Helpers that report status and progress."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from string.templatelib import Template
from typing import Literal

from tori_py_liveview import JS, attrs, classes, fragment, raw

from tori_py_liveview_ui._shared import (
    SIZES,
    TONES,
    Size,
    Tone,
    boolean,
    bounded_integer,
    event_binding,
    event_target,
    one_of,
    optional_nonempty_text,
    optional_text,
    required_text,
    selector_id,
)
from tori_py_liveview_ui.icons import icon

type SkeletonShape = Literal["text", "block", "circle"]
type ToastPlacement = Literal["top-start", "top-end", "bottom-start", "bottom-end"]

_SKELETON_SHAPES = frozenset({"text", "block", "circle"})
_TOAST_PLACEMENTS = frozenset({"top-start", "top-end", "bottom-start", "bottom-end"})
# Flash kinds the group shows, in order, with the tone each one gets.
_FLASH_TONES: dict[str, Tone] = {
    "error": "danger",
    "warning": "warning",
    "success": "success",
    "info": "info",
}
# Kinds that stay until the visitor dismisses them.
_FLASH_STICKY = frozenset({"error", "warning"})


def _role(tone: str) -> str:
    return "alert" if tone == "danger" else "status"


def _dismiss(
    name: str,
    block: str,
    button: str,
    dismissible: bool,
    dismiss_event: str | JS | None,
    dismiss_label: str,
    target: int | None,
) -> object:
    """Render the button that closes ``block``, or nothing.

    Without an event the browser hides the block; with one the page decides.
    """
    boolean(f"{name} dismissible", dismissible)
    dismiss_event = event_binding(f"{name} dismiss event", dismiss_event)
    dismiss_label = required_text(f"{name} dismiss label", dismiss_label)
    target = event_target(f"{name} target", target, dismiss_event)
    if not dismissible and dismiss_event is None:
        return raw("")
    attributes = attrs(
        {
            "type": "button",
            "class": button,
            "aria-label": dismiss_label,
            "phx-click": (
                JS().hide(to=("closest", f".{block}"))
                if dismiss_event is None
                else dismiss_event
            ),
            "phx-target": target,
        }
    )
    return t"<button{attributes}>{icon('x', size='sm')}</button>"


def alert(
    content: object,
    *,
    title: str | None = None,
    tone: Tone = "neutral",
    actions: object | None = None,
    dismissible: bool = False,
    dismiss_event: str | JS | None = None,
    dismiss_label: str = "Dismiss",
    target: int | None = None,
) -> Template:
    """Render a message in the flow of the page.

    ``dismissible`` adds a button that hides the alert in the browser. With
    ``dismiss_event`` the button pushes that event instead and the page stops
    rendering the alert.
    """
    title = optional_text("alert title", title)
    one_of("alert tone", tone, TONES)
    class_name = classes("tori-ui-alert", f"tori-ui-alert--{tone}")
    title_markup = (
        t'<h2 class="tori-ui-alert__title">{title}</h2>'
        if title is not None
        else raw("")
    )
    actions_markup = (
        t'<div class="tori-ui-alert__actions">{actions}</div>'
        if actions is not None
        else raw("")
    )
    dismiss = _dismiss(
        "alert",
        "tori-ui-alert",
        "tori-ui-alert__dismiss",
        dismissible,
        dismiss_event,
        dismiss_label,
        target,
    )
    return (
        t'<section class="{class_name}" role="{_role(tone)}">'
        t'<div class="tori-ui-alert__content">{title_markup}'
        t'<div class="tori-ui-alert__body">{content}</div>{actions_markup}</div>'
        t"{dismiss}</section>"
    )


def banner(
    content: object,
    *,
    tone: Tone = "info",
    actions: object | None = None,
    dismissible: bool = False,
    dismiss_event: str | JS | None = None,
    dismiss_label: str = "Dismiss",
    target: int | None = None,
) -> Template:
    """Render a full-width strip for a notice that concerns the whole page."""
    one_of("banner tone", tone, TONES)
    class_name = classes("tori-ui-banner", f"tori-ui-banner--{tone}")
    actions_markup = (
        t'<div class="tori-ui-banner__actions">{actions}</div>'
        if actions is not None
        else raw("")
    )
    dismiss = _dismiss(
        "banner",
        "tori-ui-banner",
        "tori-ui-banner__dismiss",
        dismissible,
        dismiss_event,
        dismiss_label,
        target,
    )
    return (
        t'<div class="{class_name}" role="{_role(tone)}">'
        t'<div class="tori-ui-banner__content">{content}</div>{actions_markup}'
        t"{dismiss}</div>"
    )


def spinner(*, label: str = "Loading", size: Size = "md") -> Template:
    """Render a spinner that announces ``label`` to screen readers."""
    label = required_text("spinner label", label)
    one_of("spinner size", size, SIZES)
    class_name = classes("tori-ui-spinner", f"tori-ui-spinner--{size}")
    return (
        t'<span class="tori-ui-spinner-status" role="status">'
        t'<span class="{class_name}" aria-hidden="true"></span>'
        t'<span class="tori-ui-visually-hidden">{label}</span></span>'
    )


def skeleton(*, shape: SkeletonShape = "text", lines: int = 1) -> Template:
    """Render a placeholder in the shape of content that is still loading.

    Skeletons are hidden from assistive technology; pair them with ``busy()``
    or a ``spinner()`` that says what is loading.
    """
    one_of("skeleton shape", shape, _SKELETON_SHAPES)
    bounded_integer("skeleton lines", lines, 1, 20)
    if shape != "text" and lines != 1:
        raise ValueError("skeleton lines require the text shape")
    class_name = classes("tori-ui-skeleton", f"tori-ui-skeleton--{shape}")
    content = (
        fragment(t'<span class="tori-ui-skeleton__line"></span>' for _ in range(lines))
        if shape == "text"
        else raw("")
    )
    return t'<div class="{class_name}" aria-hidden="true">{content}</div>'


def busy(content: object, *, busy: bool, label: str = "Loading") -> Template:
    """Mark a region as loading and cover it with a spinner while it is."""
    boolean("busy state", busy)
    label = required_text("busy label", label)
    class_name = classes("tori-ui-busy", **{"tori-ui-busy--active": busy})
    # A busy region is inert: its controls take no pointer or keyboard input.
    inner = attrs({"class": "tori-ui-busy__content", "inert": busy})
    overlay = (
        t'<div class="tori-ui-busy__overlay">{spinner(label=label)}</div>'
        if busy
        else raw("")
    )
    return (
        t'<div class="{class_name}" aria-busy="{str(busy).lower()}">'
        t"<div{inner}>{content}</div>{overlay}</div>"
    )


def toast(
    content: object,
    *,
    id: str,
    title: str | None = None,
    tone: Tone = "neutral",
    duration: int | None = 5000,
    dismiss_event: str | JS | None = None,
    dismiss_label: str = "Dismiss",
    target: int | None = None,
) -> Template:
    """Render a short message that floats above the page in a ``toast_region``.

    The toast closes itself after ``duration`` milliseconds, unless the visitor
    points at it or focuses it; ``duration=None`` keeps it until dismissed.
    Closing presses its dismiss button: by default that hides the toast in the
    browser, and with ``dismiss_event`` it tells the page to stop rendering it.
    """
    id = selector_id("toast id", id)
    title = optional_nonempty_text("toast title", title)
    one_of("toast tone", tone, TONES)
    if duration is not None:
        bounded_integer("toast duration", duration, 1000, 600000)
    dismiss = _dismiss(
        "toast",
        "tori-ui-toast",
        "tori-ui-toast__dismiss",
        True,
        dismiss_event,
        dismiss_label,
        target,
    )
    attributes = attrs(
        {
            "id": id,
            "class": classes("tori-ui-toast", f"tori-ui-toast--{tone}"),
            "role": _role(tone),
            "phx-hook": "ToriUiToast" if duration is not None else None,
            "data-tori-ui-duration": duration,
        }
    )
    title_markup = (
        t'<p class="tori-ui-toast__title">{title}</p>' if title is not None else raw("")
    )
    return (
        t'<div{attributes}><div class="tori-ui-toast__content">{title_markup}'
        t'<div class="tori-ui-toast__body">{content}</div></div>{dismiss}</div>'
    )


def toast_region(
    children: Iterable[object],
    *,
    id: str = "toasts",
    placement: ToastPlacement = "bottom-end",
    label: str = "Notifications",
) -> Template:
    """Pin toasts to a corner of the viewport. Render one region per page."""
    id = selector_id("toast region id", id)
    one_of("toast region placement", placement, _TOAST_PLACEMENTS)
    label = required_text("toast region label", label)
    class_name = classes("tori-ui-toast-region", f"tori-ui-toast-region--{placement}")
    return (
        t'<div id="{id}" class="{class_name}" role="region" aria-label="{label}">'
        t"{fragment(children)}</div>"
    )


def flash_group(
    flash: Mapping[str, str],
    *,
    id: str = "flash",
    placement: ToastPlacement = "top-end",
    label: str = "Notifications",
    duration: int | None = 5000,
) -> Template:
    """Render the page's flash messages as toasts.

    Pass ``self.flash``. The ``info``, ``success``, ``warning``, and ``error``
    kinds are shown; ``warning`` and ``error`` stay until dismissed. Closing a
    toast clears its kind through LiveView's built-in ``lv:clear-flash`` event.
    """
    if not isinstance(flash, Mapping):
        raise TypeError("flash group flash must be a mapping")
    id = selector_id("flash group id", id)
    toasts: list[Template] = []
    for kind, tone in _FLASH_TONES.items():
        message = flash.get(kind)
        if message is None:
            continue
        toast_id = f"{id}-{kind}"
        clear = JS().push("lv:clear-flash", value={"key": kind}).hide(to=f"#{toast_id}")
        toasts.append(
            toast(
                message,
                id=toast_id,
                tone=tone,
                duration=None if kind in _FLASH_STICKY else duration,
                dismiss_event=clear,
            )
        )
    return toast_region(toasts, id=id, placement=placement, label=label)


def connection_status(
    *,
    message: str = "Connection lost. Reconnecting.",
) -> Template:
    """Tell the visitor when the page has lost its connection to the server.

    Render it once inside the page. It stays hidden while LiveView is
    connected and appears while the client reconnects.
    """
    message = required_text("connection status message", message)
    return (
        t'<div class="tori-ui-connection-status" role="status">'
        t'<span class="tori-ui-spinner tori-ui-spinner--sm" aria-hidden="true">'
        t"</span>{message}</div>"
    )


__all__ = [
    "alert",
    "banner",
    "busy",
    "connection_status",
    "flash_group",
    "skeleton",
    "spinner",
    "toast",
    "toast_region",
]
