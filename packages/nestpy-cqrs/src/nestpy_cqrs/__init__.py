"""Nestpy integration for cqrs-core."""

from nestpy_cqrs.bindings import (
    CqrsHandlerBinding,
    bind_command_handler,
    bind_event_handler,
    bind_query_handler,
)
from nestpy_cqrs.decorators import command_handler, event_handler, query_handler
from nestpy_cqrs.errors import (
    CqrsConfigurationError,
    CqrsHandlerExitCancellationError,
    CqrsHandlerExitError,
    CqrsLifecycleError,
    CqrsPipelineStateError,
    NestpyCqrsError,
)
from nestpy_cqrs.invocation import (
    CqrsCompletionMapper,
    CqrsInterceptorBinding,
    CqrsInterceptorPhase,
    CqrsInvocationCompletion,
    CqrsInvocationContext,
    CqrsInvocationInterceptor,
    CqrsNext,
    CqrsScopeCompletion,
    use_cqrs_interceptors,
)
from nestpy_cqrs.module import CqrsModule
from nestpy_cqrs.options import CqrsModuleOptions, TransportFactory

__all__ = [
    "CqrsConfigurationError",
    "CqrsCompletionMapper",
    "CqrsHandlerBinding",
    "CqrsHandlerExitCancellationError",
    "CqrsHandlerExitError",
    "CqrsInterceptorBinding",
    "CqrsInterceptorPhase",
    "CqrsInvocationCompletion",
    "CqrsInvocationContext",
    "CqrsInvocationInterceptor",
    "CqrsLifecycleError",
    "CqrsNext",
    "CqrsPipelineStateError",
    "CqrsScopeCompletion",
    "CqrsModule",
    "CqrsModuleOptions",
    "NestpyCqrsError",
    "TransportFactory",
    "bind_command_handler",
    "bind_event_handler",
    "bind_query_handler",
    "command_handler",
    "event_handler",
    "query_handler",
    "use_cqrs_interceptors",
]
