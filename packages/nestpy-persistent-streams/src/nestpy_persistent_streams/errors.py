"""Bounded public diagnostics for persistent stream integration."""


class NestpyPersistentStreamsError(Exception):
    """Base integration error with a stable diagnostic code."""

    diagnostic_code = "persistent_streams.error"


class StreamConfigurationError(NestpyPersistentStreamsError):
    """Raised when immutable stream configuration is invalid."""

    diagnostic_code = "persistent_streams.invalid_configuration"


class StreamHandlerCompilationError(NestpyPersistentStreamsError):
    """Raised when stream handler metadata or signatures are invalid."""

    diagnostic_code = "persistent_streams.invalid_handler"


class StreamInvocationError(NestpyPersistentStreamsError):
    """Raised when one record cannot complete safely."""

    diagnostic_code = "persistent_streams.invocation_failed"


class StreamRuntimeError(NestpyPersistentStreamsError):
    """Raised for lifecycle, admission, or adapter failures."""

    diagnostic_code = "persistent_streams.runtime_failed"


class StreamPublicationSaturatedError(StreamRuntimeError):
    """Raised when the runtime publication admission bound is full."""

    diagnostic_code = "persistent_streams.publication_saturated"


__all__ = [
    "NestpyPersistentStreamsError",
    "StreamConfigurationError",
    "StreamHandlerCompilationError",
    "StreamInvocationError",
    "StreamPublicationSaturatedError",
    "StreamRuntimeError",
]
