"""Bounded public diagnostics for persistent stream integration."""


class ToriPyPersistentStreamsError(Exception):
    """Base integration error with a stable diagnostic code."""

    diagnostic_code = "tori_py_persistent_streams_core.error"


class StreamConfigurationError(ToriPyPersistentStreamsError):
    """Raised when immutable stream configuration is invalid."""

    diagnostic_code = "tori_py_persistent_streams_core.invalid_configuration"


class StreamHandlerCompilationError(ToriPyPersistentStreamsError):
    """Raised when stream handler metadata or signatures are invalid."""

    diagnostic_code = "tori_py_persistent_streams_core.invalid_handler"


class StreamInvocationError(ToriPyPersistentStreamsError):
    """Raised when one record cannot complete safely."""

    diagnostic_code = "tori_py_persistent_streams_core.invocation_failed"


class StreamRuntimeError(ToriPyPersistentStreamsError):
    """Raised for lifecycle, admission, or adapter failures."""

    diagnostic_code = "tori_py_persistent_streams_core.runtime_failed"


class StreamPublicationSaturatedError(StreamRuntimeError):
    """Raised when the runtime publication admission bound is full."""

    diagnostic_code = "tori_py_persistent_streams_core.publication_saturated"


__all__ = [
    "ToriPyPersistentStreamsError",
    "StreamConfigurationError",
    "StreamHandlerCompilationError",
    "StreamInvocationError",
    "StreamPublicationSaturatedError",
    "StreamRuntimeError",
]
