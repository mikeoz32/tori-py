"""Transport-neutral WebSocket gateway contracts."""

from tori_py.websocket.context import WebSocketContext, current_websocket_context
from tori_py.websocket.errors import WebSocketForbidden
from tori_py.websocket.pipeline import (
    WebSocketPipelineAdapter,
    WebSocketPipelineExecutor,
)
from tori_py.websocket.routes import (
    WebSocketParameterPlan,
    WebSocketPlan,
    bind_websocket_routes,
    compile_websocket_gateway,
    compile_websocket_routes,
)

__all__ = [
    "WebSocketContext",
    "WebSocketForbidden",
    "WebSocketPipelineAdapter",
    "WebSocketPipelineExecutor",
    "WebSocketParameterPlan",
    "WebSocketPlan",
    "bind_websocket_routes",
    "compile_websocket_gateway",
    "compile_websocket_routes",
    "current_websocket_context",
]
