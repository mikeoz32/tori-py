"""Optional microservices integration for Nestpy."""

from nestpy_microservices.errors import (
    IdentityValidationError,
    MicroservicesError,
    OptionalDependencyError,
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

__all__ = [
    "EventIdentity",
    "IdentityValidationError",
    "MessageLimits",
    "MicroservicesError",
    "OptionalDependencyError",
    "ReplyRoute",
    "RpcTarget",
    "ServiceIdentity",
    "WireValidationError",
    "require_future_deadline",
    "require_uuid",
    "require_utc",
    "utc_now",
]
