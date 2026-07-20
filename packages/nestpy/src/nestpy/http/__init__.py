"""Framework-owned HTTP execution contracts without a transport dependency."""

from nestpy.http.context import HttpContext, current_http_context
from nestpy.http.errors import HttpException
from nestpy.http.pipeline import HttpPipelineAdapter, PipelineExecutor
from nestpy.http.routes import ParameterPlan, RoutePlan, bind_routes, compile_routes
from nestpy.http.validation import MsgspecValidationPipe

__all__ = [
    "HttpContext",
    "HttpException",
    "HttpPipelineAdapter",
    "MsgspecValidationPipe",
    "ParameterPlan",
    "PipelineExecutor",
    "RoutePlan",
    "bind_routes",
    "compile_routes",
    "current_http_context",
]
