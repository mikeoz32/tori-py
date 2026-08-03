"""Optional microservices integration for Nestpy."""

from nestpy_microservices.codec import MessageCodec, MsgspecJsonMessageCodec
from nestpy_microservices.errors import (
    IdentityValidationError,
    MicroservicesError,
    OptionalDependencyError,
    WireDeadlineError,
    WireDecodingError,
    WireEncodingError,
    WireSizeLimitError,
    WireValidationError,
)
from nestpy_microservices.identities import (
    EventIdentity,
    MessageLimits,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    require_future_deadline,
    require_utc,
    require_uuid,
    utc_now,
)
from nestpy_microservices.wire import (
    RESULT_MISSING,
    EventEnvelope,
    MessageMetadata,
    RemoteRpcErrorData,
    RpcRequestEnvelope,
    RpcResponseEnvelope,
)

__all__ = [
    "EventIdentity",
    "EventEnvelope",
    "IdentityValidationError",
    "MessageCodec",
    "MessageLimits",
    "MessageMetadata",
    "MicroservicesError",
    "MsgspecJsonMessageCodec",
    "OptionalDependencyError",
    "ReplyRoute",
    "RpcTarget",
    "RpcRequestEnvelope",
    "RpcResponseEnvelope",
    "RemoteRpcErrorData",
    "RESULT_MISSING",
    "ServiceIdentity",
    "WireDeadlineError",
    "WireDecodingError",
    "WireEncodingError",
    "WireSizeLimitError",
    "WireValidationError",
    "require_future_deadline",
    "require_uuid",
    "require_utc",
    "utc_now",
]
