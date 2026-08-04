from __future__ import annotations

import nestpy_microservices
from nestpy_microservices import MicroservicesError, OptionalDependencyError


def test_root_facade_is_exact_and_typed() -> None:
    assert set(nestpy_microservices.__all__) == {
        "EventIdentity",
        "EventEnvelope",
        "IdentityValidationError",
        "Context",
        "EventDispatchMode",
        "EventContext",
        "EventHandlerMetadata",
        "EventHandlerPlan",
        "EncodedDelivery",
        "ClientTransport",
        "ClientClusterRoot",
        "ClientsModule",
        "ServiceCluster",
        "ServiceClusterOptions",
        "ServiceProxy",
        "DeliveryDispatcher",
        "HandlerCompilationError",
        "DuplicateSettlementError",
        "EventSubscription",
        "InMemoryBroker",
        "InMemoryClientTransport",
        "InMemoryServerTransport",
        "Header",
        "Headers",
        "Inject",
        "InvocationCompletion",
        "MessageCodec",
        "MessageAuthorizationError",
        "MessageConfigurationError",
        "MessageContext",
        "MessageInvocation",
        "MessageInvocationError",
        "MessagePipelineExecutor",
        "MicroservicesModule",
        "MicroservicesOptions",
        "MicroservicesRoot",
        "MessageLimits",
        "MessageMetadata",
        "MessageParameterPlan",
        "MessageRejectedError",
        "MessageRetryableError",
        "MicroservicesError",
        "MsgspecJsonMessageCodec",
        "OptionalDependencyError",
        "RemoteRpcError",
        "RpcClientError",
        "RpcOutcomeUnknownError",
        "RpcProtocolError",
        "RpcTimeoutError",
        "Payload",
        "PipelinePlan",
        "ReplyRoute",
        "RemoteRpcErrorData",
        "RESULT_MISSING",
        "RpcHandlerPlan",
        "RpcMetadata",
        "RpcContext",
        "RpcRequestEnvelope",
        "RpcResponseEnvelope",
        "RpcTarget",
        "ServiceIdentity",
        "ServiceHandlerRegistry",
        "ServerTransportFactory",
        "ServiceRuntime",
        "SettlementRecommendation",
        "Publication",
        "PublicationReceipt",
        "ServerTransport",
        "TransportCapacityError",
        "TransportCorrelationError",
        "TransportError",
        "TransportIndeterminateError",
        "TransportRejectedError",
        "TransportStateError",
        "TransportStatus",
        "TransportStatusEvent",
        "TransportTimeoutError",
        "TransportUnavailableError",
        "TransportUnroutableError",
        "RabbitMqModule",
        "RabbitMqConnectionManager",
        "BindingDeclaration",
        "ExchangeDeclaration",
        "RabbitMqOptions",
        "RabbitMqRoot",
        "RabbitMqTopology",
        "RabbitMqTransport",
        "RabbitMqStatus",
        "QueueDeclaration",
        "WireDeadlineError",
        "WireDecodingError",
        "WireEncodingError",
        "WireSizeLimitError",
        "WireValidationError",
        "require_future_deadline",
        "require_uuid",
        "require_utc",
        "utc_now",
        "validate_alias",
        "validate_version",
        "compile_controller_message_handlers",
        "compile_discovered_service_handlers",
        "compile_service_handler_registry",
        "event_handler",
        "rpc",
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

    assert "require_aio_pika" in rabbitmq.__all__
    assert "RabbitMqOptions" in rabbitmq.__all__
    assert "aio_pika" not in sys.modules
