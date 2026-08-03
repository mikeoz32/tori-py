from __future__ import annotations

import nestpy_microservices
from nestpy_microservices import MicroservicesError, OptionalDependencyError


def test_root_facade_is_exact_and_typed() -> None:
    assert set(nestpy_microservices.__all__) == {
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
        "RemoteRpcErrorData",
        "RESULT_MISSING",
        "RpcRequestEnvelope",
        "RpcResponseEnvelope",
        "RpcTarget",
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
    }
    assert all(
        hasattr(nestpy_microservices, name) for name in nestpy_microservices.__all__
    )
    assert issubclass(OptionalDependencyError, MicroservicesError)
    assert MicroservicesError.diagnostic_code == "microservices.error"
    assert (
        OptionalDependencyError("aio-pika", "rabbitmq").diagnostic_code
        == "microservices.optional_dependency"
    )


def test_rabbitmq_facade_is_lazy() -> None:
    import sys

    import nestpy_microservices.rabbitmq as rabbitmq

    assert set(rabbitmq.__all__) == {"require_aio_pika"}
    assert "aio_pika" not in sys.modules
