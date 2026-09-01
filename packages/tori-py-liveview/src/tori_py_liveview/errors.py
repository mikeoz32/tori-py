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


__all__ = ["LiveViewConfigurationError", "LiveViewError", "UnknownEventError"]
