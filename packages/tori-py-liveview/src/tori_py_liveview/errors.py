"""Public LiveView integration failures."""

from tori_py import ToriPyError


class LiveViewError(ToriPyError):
    """Base class for ToriPy LiveView failures."""

    code = "liveview.error"


class LiveViewConfigurationError(LiveViewError):
    """Raised when a LiveView declaration is invalid."""

    code = "liveview.configuration_error"


class UnknownEventError(LiveViewError):
    """Raised by a page for an event it does not handle."""

    code = "liveview.unknown_event"

    def __init__(self, event: str) -> None:
        super().__init__(f"Unknown LiveView event: {event}")


class UnknownInfoError(LiveViewError):
    """Raised by a page for an info message it does not handle."""

    code = "liveview.unknown_info"

    def __init__(self, info: str) -> None:
        super().__init__(f"Unknown LiveView info: {info}")


class UnknownAsyncError(LiveViewError):
    """Raised by a page or component for an async result it does not handle."""

    code = "liveview.unknown_async"

    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown LiveView async result: {name}")


__all__ = [
    "LiveViewConfigurationError",
    "LiveViewError",
    "UnknownAsyncError",
    "UnknownEventError",
    "UnknownInfoError",
]
