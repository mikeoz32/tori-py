"""Stable package errors for the Nestpy microservices integration."""

from __future__ import annotations

from collections.abc import Mapping


class MicroservicesError(Exception):
    """Base error for failures owned by the microservices integration."""

    diagnostic_code = "microservices.error"


class OptionalDependencyError(MicroservicesError):
    """Raised when an optional transport dependency is used without its extra."""

    diagnostic_code = "microservices.optional_dependency"

    def __init__(self, dependency: str, extra: str) -> None:
        self.dependency = dependency
        self.extra = extra
        super().__init__(
            f"{dependency!r} is required for this feature; install the "
            f"'nestpy-microservices[{extra}]' extra"
        )


class IdentityValidationError(MicroservicesError, ValueError):
    """Raised when a published service or message identity is invalid."""

    diagnostic_code = "microservices.identity_validation"


class WireValidationError(MicroservicesError, ValueError):
    """Raised when a transport-neutral wire value violates its contract."""

    diagnostic_code = "microservices.wire_validation"


class WireEncodingError(WireValidationError):
    """Raised when a value cannot be encoded under the wire contract."""

    diagnostic_code = "microservices.wire_encoding"


class WireDecodingError(WireValidationError):
    """Raised when bytes do not contain a valid wire envelope."""

    diagnostic_code = "microservices.wire_decoding"


class WireSizeLimitError(WireValidationError):
    """Raised before decoding when a wire value exceeds configured limits."""

    diagnostic_code = "microservices.wire_size_limit"


class WireDeadlineError(WireValidationError):
    """Raised when an envelope deadline violates the RPC contract."""

    diagnostic_code = "microservices.wire_deadline"


class HandlerCompilationError(MicroservicesError, ValueError):
    """Raised when message handler metadata or signatures are invalid."""

    diagnostic_code = "microservices.handler_compilation"


class MessageInvocationError(MicroservicesError):
    """Base error for message binding and pipeline invocation failures."""

    diagnostic_code = "microservices.invocation"


class MessageAuthorizationError(MessageInvocationError):
    """Raised when a message guard denies execution."""

    diagnostic_code = "microservices.authorization"


class MessageConfigurationError(MessageInvocationError):
    """Raised when a handler result violates its message contract."""

    diagnostic_code = "microservices.invocation_configuration"


class MessageRetryableError(MessageInvocationError):
    """Explicitly retryable message failure."""

    diagnostic_code = "microservices.retryable"


class MessageRejectedError(MessageInvocationError):
    """Explicit terminal message rejection."""

    diagnostic_code = "microservices.rejected"


class PublicRpcError(MessageInvocationError):
    """An application error explicitly approved for exposure to RPC callers."""

    diagnostic_code = "microservices.public_rpc"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(code, str) or not code:
            raise ValueError("public RPC error code must be a non-empty string")
        if not isinstance(message, str) or not message:
            raise ValueError("public RPC error message must be a non-empty string")
        if not isinstance(retryable, bool):
            raise ValueError("public RPC error retryable must be boolean")
        if details is not None and not isinstance(details, Mapping):
            raise TypeError("public RPC error details must be a mapping")
        self.code = code
        self.public_message = message
        self.retryable = retryable
        self.details = {} if details is None else dict(details)
        super().__init__(message)


class TransportError(MicroservicesError):
    """Base error for transport-owned failures."""

    diagnostic_code = "microservices.transport"


class TransportUnavailableError(TransportError):
    """The transport cannot currently accept or deliver a publication."""

    diagnostic_code = "microservices.transport_unavailable"


class TransportTimeoutError(TransportError):
    """A transport operation exceeded its caller-provided deadline."""

    diagnostic_code = "microservices.transport_timeout"


class TransportIndeterminateError(TransportError):
    """The transport cannot determine whether an operation was accepted."""

    diagnostic_code = "microservices.transport_indeterminate"


class TransportRejectedError(TransportError):
    """The transport rejected a publication before delivery."""

    diagnostic_code = "microservices.transport_rejected"


class TransportUnroutableError(TransportError):
    """A mandatory publication had no matching route."""

    diagnostic_code = "microservices.transport_unroutable"


class TransportCorrelationError(TransportError):
    """A reply has no currently pending or has already completed correlation."""

    diagnostic_code = "microservices.transport_correlation"


class TransportStateError(TransportError):
    """A transport operation is invalid for its current lifecycle state."""

    diagnostic_code = "microservices.transport_state"


class DuplicateSettlementError(TransportError):
    """A delivery was settled more than once."""

    diagnostic_code = "microservices.duplicate_settlement"


class TransportCapacityError(TransportError):
    """A bounded in-memory transport queue or pending map is full."""

    diagnostic_code = "microservices.transport_capacity"


class RabbitMqError(MicroservicesError):
    """Base error for the optional RabbitMQ adapter."""

    diagnostic_code = "microservices.rabbitmq"


class RabbitMqConnectionError(RabbitMqError):
    """Connection or channel acquisition failed."""

    diagnostic_code = "microservices.rabbitmq_connection"


class RabbitMqTopologyError(RabbitMqError):
    """A topology declaration failed or conflicted with broker state."""

    diagnostic_code = "microservices.rabbitmq_topology"


class RpcClientError(MicroservicesError):
    """Base error for client-side RPC outcomes."""

    diagnostic_code = "microservices.rpc_client"


class RpcTimeoutError(RpcClientError):
    """The local RPC deadline elapsed before a reply completed the call."""

    diagnostic_code = "microservices.rpc_timeout"


class RpcOutcomeUnknownError(RpcClientError):
    """The client lost reply transport after publication became uncertain."""

    diagnostic_code = "microservices.rpc_outcome_unknown"


class RpcProtocolError(RpcClientError):
    """The reply was malformed or failed declared result decoding."""

    diagnostic_code = "microservices.rpc_protocol"


class RemoteRpcError(RpcClientError):
    """A remote service returned a stable typed error."""

    diagnostic_code = "microservices.remote_rpc_error"

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = {} if details is None else dict(details)
        super().__init__(f"{code}: {message}")


__all__ = [
    "HandlerCompilationError",
    "IdentityValidationError",
    "MessageAuthorizationError",
    "MessageConfigurationError",
    "MessageInvocationError",
    "MessageRejectedError",
    "MessageRetryableError",
    "MicroservicesError",
    "OptionalDependencyError",
    "PublicRpcError",
    "DuplicateSettlementError",
    "TransportCapacityError",
    "TransportCorrelationError",
    "TransportError",
    "TransportIndeterminateError",
    "TransportRejectedError",
    "TransportStateError",
    "TransportTimeoutError",
    "TransportUnavailableError",
    "TransportUnroutableError",
    "RemoteRpcError",
    "RabbitMqConnectionError",
    "RabbitMqError",
    "RabbitMqTopologyError",
    "RpcClientError",
    "RpcOutcomeUnknownError",
    "RpcProtocolError",
    "RpcTimeoutError",
    "WireDeadlineError",
    "WireDecodingError",
    "WireEncodingError",
    "WireSizeLimitError",
    "WireValidationError",
]
