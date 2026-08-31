"""Transport-neutral WebSocket execution errors."""

from tori_py.core.errors import ToriPyError


class WebSocketForbidden(ToriPyError):
    """Signal that a guard denied an unaccepted WebSocket connection."""

    code = "websocket.forbidden"


__all__ = ["WebSocketForbidden"]
