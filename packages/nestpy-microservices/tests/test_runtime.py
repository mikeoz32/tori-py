from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from inspect import signature
from typing import Annotated, Protocol, cast
from uuid import uuid4

import msgspec
import pytest
from nestpy import (
    DiscoveryService,
    ModulesContainer,
    ModuleSpec,
    NestApplication,
    ScopeFinalizationError,
    WorkScopeFactory,
    controller,
    module,
    use_guard,
    use_interceptor,
)
from nestpy.testing import TestingModule
from nestpy_microservices.errors import PublicRpcError

from nestpy_microservices import (
    EncodedDelivery,
    EventContext,
    EventDispatcher,
    EventDispatchMode,
    EventEnvelope,
    EventIdentity,
    EventSubscription,
    InMemoryBroker,
    InMemoryClientTransport,
    InMemoryServerTransport,
    MessageCodec,
    MessageContext,
    MessageLimits,
    MicroservicesModule,
    MicroservicesOptions,
    MsgspecJsonMessageCodec,
    Payload,
    Publication,
    PublicationReceipt,
    RabbitMqModule,
    RabbitMqOptions,
    RabbitMqTransport,
    RpcContext,
    RpcRequestEnvelope,
    RpcTarget,
    ServiceIdentity,
    ServiceRuntime,
    SettlementRecommendation,
    TransportIndeterminateError,
    TransportStateError,
    TransportStatus,
    TransportStatusEvent,
    TransportUnroutableError,
    event_handler,
    rpc,
    rpc_call,
    service_contract,
)

SERVICE = ServiceIdentity("kinker", "members", 1)
OTHER_SERVICE = ServiceIdentity("kinker", "groups", 1)


class ContractPayload(msgspec.Struct):
    value: str


@service_contract(OTHER_SERVICE)
class OtherServiceContract(Protocol):
    @rpc_call("contract-call", payload=ContractPayload)
    async def call(self, value: str) -> str: ...


class EmptyDiscovery:
    def get_controllers(self):
        return ()


class EmptyModules:
    pass


@dataclass
class Factory:
    broker: InMemoryBroker
    created: int = 0

    def create(self, identity, options):
        del identity, options
        self.created += 1
        return InMemoryServerTransport(self.broker, SERVICE)


class RecordingTransport:
    def __init__(self) -> None:
        self.status = TransportStatus.CREATED
        self.publications: list[Publication] = []
        self.subscriptions: tuple[EventSubscription, ...] = ()
        self.publish_error: Exception | None = None

    async def prepare(
        self,
        *,
        rpc_methods: Iterable[str] = (),
        subscriptions: Iterable[EventSubscription] = (),
    ) -> None:
        tuple(rpc_methods)
        self.subscriptions = tuple(subscriptions)
        self.status = TransportStatus.PREPARED

    async def start(self, dispatcher) -> None:
        self.dispatcher = dispatcher
        self.status = TransportStatus.RUNNING

    async def settle(self, delivery, outcome) -> None:
        del delivery, outcome

    async def publish_reply(self, publication: Publication) -> PublicationReceipt:
        self.publications.append(publication)
        if self.publish_error is not None:
            raise self.publish_error
        return PublicationReceipt(publication.message_id, datetime.now(UTC), True)

    async def stop_intake(self) -> None:
        self.status = TransportStatus.QUIESCING

    async def close(self) -> None:
        self.status = TransportStatus.CLOSED

    async def statuses(self) -> AsyncIterator[TransportStatusEvent]:
        if False:
            yield TransportStatusEvent(self.status, datetime.now(UTC))

    def unwrap(self) -> object:
        return self


@dataclass
class RecordingFactory:
    transport: RecordingTransport

    def create(self, identity, options):
        del identity, options
        return self.transport


@dataclass
class Shutdown:
    value: float = 1.0

    def remaining(self) -> float:
        return self.value


def encoded_request_delivery(
    codec: MessageCodec,
    request: RpcRequestEnvelope,
    *,
    routing_key: str | None = None,
    message_id=None,
    correlation_id=None,
) -> EncodedDelivery:
    return EncodedDelivery(
        message_id=request.message_id if message_id is None else message_id,
        routing_key=routing_key
        or RpcTarget(
            request.service, request.method, request.schema_version
        ).routing_key,
        body=codec.encode_request(request),
        headers={},
        received_at=datetime.now(UTC),
        correlation_id=(
            request.correlation_id if correlation_id is None else correlation_id
        ),
        reply_to=request.reply_to,
    )


def test_options_validate_finite_service_limits() -> None:
    with pytest.raises(ValueError):
        MicroservicesOptions(max_concurrency=2, max_inflight_deliveries=1)
    with pytest.raises(ValueError):
        MicroservicesOptions(max_accepted_rpc_timeout=float("inf"))

    options = MicroservicesOptions(max_concurrency=2, max_inflight_deliveries=4)
    assert options.max_concurrency == 2


def test_module_materialization_only_captures_configuration() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)
    descriptor = MicroservicesModule.for_root(SERVICE, transport=factory)

    assert factory.created == 0
    spec = cast(ModuleSpec, descriptor.factory())
    assert factory.created == 0
    assert len(tuple(spec.providers)) == 2
    assert EventDispatcher not in spec.exports


def test_module_root_does_not_expose_a_dispatcher_bypass() -> None:
    assert "dispatcher" not in signature(MicroservicesModule.for_root).parameters


@pytest.mark.asyncio
async def test_runtime_starts_after_bootstrap_and_quiesces_before_close() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)

    async def dispatch(delivery):
        del delivery
        return SettlementRecommendation.ACK

    runtime = ServiceRuntime(
        SERVICE,
        transport_factory=factory,
        discovery=cast(DiscoveryService, EmptyDiscovery()),
        modules=cast(ModulesContainer, EmptyModules()),
        dispatcher=dispatch,
    )

    await runtime.on_application_bootstrap()
    assert runtime.accepting
    assert runtime.transport is not None
    assert runtime.transport.status is TransportStatus.RUNNING
    assert factory.created == 1

    await runtime.on_application_quiesce(Shutdown())
    assert not runtime.accepting
    assert runtime.transport.status is TransportStatus.QUIESCING
    await runtime.close()
    assert runtime.transport is None
    await broker.close()


@pytest.mark.asyncio
async def test_module_installs_runtime_in_nest_application_lifecycle() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)
    application = await NestApplication.create(
        MicroservicesModule.for_root(SERVICE, transport=factory)
    )

    await application.start()
    assert factory.created == 1
    await application.shutdown()
    assert application.state.value == "stopped"
    await broker.close()


@pytest.mark.asyncio
async def test_runtime_rejects_a_handler_from_another_service_contract() -> None:
    broker = InMemoryBroker()
    factory = Factory(broker)

    @controller()
    class WrongServiceController:
        @rpc(OtherServiceContract.call)
        async def call(
            self,
            payload: Annotated[ContractPayload, Payload()],
        ) -> str:
            return payload.value

    @module(
        imports=[MicroservicesModule.for_root(SERVICE, transport=factory)],
        controllers=[WrongServiceController],
    )
    class ApplicationModule:
        pass

    application = await NestApplication.create(ApplicationModule)

    with pytest.raises(TransportStateError, match="belongs to"):
        await application.start()

    assert factory.created == 0
    await broker.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_identity",
    [SERVICE, ServiceIdentity("kinker", "groups", 1)],
)
async def test_application_rejects_multiple_service_roots_before_startup(
    second_identity: ServiceIdentity,
) -> None:
    broker = InMemoryBroker()
    first_factory = Factory(broker)
    second_factory = Factory(broker)

    @module(
        imports=[
            MicroservicesModule.for_root(
                SERVICE,
                transport=first_factory,
                key="first",
            ),
            MicroservicesModule.for_root(
                second_identity,
                transport=second_factory,
                key="second",
            ),
        ]
    )
    class ApplicationModule:
        pass

    application = await NestApplication.create(ApplicationModule)

    with pytest.raises(TransportStateError, match="at most one"):
        await application.start()

    assert first_factory.created == 0
    assert second_factory.created == 0
    await broker.close()


@pytest.mark.asyncio
async def test_rabbitmq_module_wires_transport_factories() -> None:
    application = await NestApplication.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RabbitMqTransport(),
            imports=(RabbitMqModule.for_root(RabbitMqOptions("amqp://localhost")),),
        )
    )

    assert application.state.value == "compiled"


@pytest.mark.asyncio
async def test_module_default_dispatcher_executes_compiled_rpc() -> None:
    broker = InMemoryBroker()

    @controller()
    class Controller:
        @rpc("ping")
        async def ping(self, payload: Annotated[str, Payload()]) -> str:
            return payload.upper()

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    factory = Factory(broker)
    application = await NestApplication.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=factory,
            imports=(ApplicationModule,),
        )
    )
    await application.start()
    client = InMemoryClientTransport(broker)
    await client.start()
    codec: MessageCodec = MsgspecJsonMessageCodec()
    correlation_id = uuid4()
    created_at = datetime.now(UTC)
    request = RpcRequestEnvelope(
        message_id=uuid4(),
        service=SERVICE,
        method="ping",
        schema_version=1,
        created_at=created_at,
        deadline_at=created_at + timedelta(seconds=5),
        correlation_id=correlation_id,
        reply_to=client.reply_to,
        payload="hello",
    )
    target = RpcTarget(SERVICE, "ping", 1)
    await client.publish_rpc(
        target,
        Publication(
            message_id=request.message_id,
            routing_key=target.routing_key,
            body=codec.encode_request(request),
            headers={},
            reply_to=client.reply_to,
            correlation_id=correlation_id,
        ),
    )
    response = await anext(client.replies())

    decoded = codec.decode_response(response.body)
    assert decoded.result == "HELLO"
    await client.close()
    await application.shutdown()
    await broker.close()


@pytest.mark.asyncio
async def test_rpc_admission_is_exact_terminal_and_pre_scope() -> None:
    calls: list[object] = []

    @controller()
    class Controller:
        @rpc("known", schema_version=2)
        async def known(self, payload: Annotated[object, Payload()]) -> object:
            calls.append(payload)
            return payload

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    transport = RecordingTransport()
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            options=MicroservicesOptions(max_accepted_rpc_timeout=2),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    codec: MessageCodec = MsgspecJsonMessageCodec()
    created_at = datetime.now(UTC)
    request = RpcRequestEnvelope(
        message_id=uuid4(),
        service=SERVICE,
        method="known",
        schema_version=2,
        created_at=created_at,
        deadline_at=created_at + timedelta(seconds=1),
        correlation_id=uuid4(),
        payload={"value": 1},
    )

    malformed = EncodedDelivery(
        request.message_id,
        RpcTarget(SERVICE, "known", 2).routing_key,
        b"not-json",
        {},
        datetime.now(UTC),
    )
    mismatch = encoded_request_delivery(
        codec, request, routing_key=f"{SERVICE.label}.other"
    )
    message_mismatch = encoded_request_delivery(codec, request, message_id=uuid4())
    correlation_mismatch = encoded_request_delivery(
        codec, request, correlation_id=uuid4()
    )
    valid_delivery = encoded_request_delivery(codec, request)
    missing_correlation = replace(valid_delivery, correlation_id=None)
    missing_reply_route = replace(valid_delivery, reply_to=None)
    too_long = RpcRequestEnvelope(
        message_id=uuid4(),
        service=SERVICE,
        method="known",
        schema_version=2,
        created_at=created_at,
        deadline_at=created_at + timedelta(seconds=3),
        correlation_id=uuid4(),
        payload={},
    )

    for delivery in (
        malformed,
        mismatch,
        message_mismatch,
        correlation_mismatch,
        missing_correlation,
        missing_reply_route,
        encoded_request_delivery(codec, too_long),
    ):
        completion = await runtime._dispatch_message(delivery)
        assert completion.recommendation is SettlementRecommendation.REJECT

    assert calls == []
    assert transport.publications == []
    await application.close()


@pytest.mark.asyncio
async def test_rpc_admission_returns_stable_deadline_method_and_schema_errors() -> None:
    @controller()
    class Controller:
        @rpc("known", schema_version=2)
        async def known(self, payload: Annotated[object, Payload()]) -> object:
            raise AssertionError("admission failures must not execute the handler")

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    transport = RecordingTransport()
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    codec = MsgspecJsonMessageCodec()

    requests = []
    stale_created = datetime.now(UTC) - timedelta(seconds=2)
    requests.append(
        RpcRequestEnvelope(
            uuid4(),
            SERVICE,
            "known",
            2,
            stale_created,
            stale_created + timedelta(seconds=1),
            uuid4(),
        )
    )
    now = datetime.now(UTC)
    requests.append(
        RpcRequestEnvelope(
            uuid4(), SERVICE, "missing", 1, now, now + timedelta(seconds=1), uuid4()
        )
    )
    requests.append(
        RpcRequestEnvelope(
            uuid4(), SERVICE, "known", 1, now, now + timedelta(seconds=1), uuid4()
        )
    )

    for request in requests:
        completion = await runtime._dispatch_message(
            encoded_request_delivery(codec, request)
        )
        assert completion.recommendation is SettlementRecommendation.ACK

    errors = [codec.decode_response(item.body).error for item in transport.publications]
    assert [error.code for error in errors if error is not None] == [
        "deadline_exceeded",
        "method_not_found",
        "unsupported_schema",
    ]
    await application.close()


@pytest.mark.asyncio
async def test_rpc_errors_are_sanitized_and_definitive_replies_ack() -> None:
    @controller()
    class Controller:
        @rpc("normal")
        async def normal(self, payload: Annotated[object, Payload()]) -> object:
            return payload

        @rpc("private")
        async def private(self, payload: Annotated[object, Payload()]) -> object:
            raise RuntimeError("database password is hunter2")

        @rpc("public")
        async def public(self, payload: Annotated[object, Payload()]) -> object:
            raise PublicRpcError(
                "profile_conflict",
                "The profile already exists.",
                details={"field": "handle"},
            )

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    transport = RecordingTransport()
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    codec = MsgspecJsonMessageCodec()
    now = datetime.now(UTC)

    for method in ("normal", "private", "public"):
        request = RpcRequestEnvelope(
            uuid4(), SERVICE, method, 1, now, now + timedelta(seconds=1), uuid4()
        )
        completion = await runtime._dispatch_message(
            encoded_request_delivery(codec, request)
        )
        assert completion.recommendation is SettlementRecommendation.ACK

    normal = codec.decode_response(transport.publications[0].body)
    private = codec.decode_response(transport.publications[1].body).error
    public = codec.decode_response(transport.publications[2].body).error
    assert normal.result is None
    assert private is not None
    assert private.code == "internal_error"
    assert "hunter2" not in private.message
    assert public is not None
    assert (public.code, public.message, dict(public.details)) == (
        "profile_conflict",
        "The profile already exists.",
        {"field": "handle"},
    )

    transport.publish_error = TransportUnroutableError("reply route is gone")
    request = RpcRequestEnvelope(
        uuid4(), SERVICE, "normal", 1, now, now + timedelta(seconds=1), uuid4()
    )
    completion = await runtime._dispatch_message(
        encoded_request_delivery(codec, request)
    )
    assert completion.recommendation is SettlementRecommendation.ACK
    await application.close()


@pytest.mark.asyncio
async def test_scope_finalization_uncertainty_publishes_no_reply() -> None:
    @controller()
    class Controller:
        @rpc("cleanup")
        async def cleanup(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    transport = RecordingTransport()
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    underlying_scopes = runtime._work_scopes
    assert underlying_scopes is not None

    class FailingScopes:
        async def run_in(self, module_id, operation):
            await underlying_scopes.run_in(module_id, operation)
            raise ScopeFinalizationError(None, (RuntimeError("cleanup failed"),))

    runtime._work_scopes = cast(WorkScopeFactory, FailingScopes())
    now = datetime.now(UTC)
    request = RpcRequestEnvelope(
        uuid4(), SERVICE, "cleanup", 1, now, now + timedelta(seconds=1), uuid4()
    )
    completion = await runtime._dispatch_message(
        encoded_request_delivery(MsgspecJsonMessageCodec(), request)
    )

    assert completion.recommendation is SettlementRecommendation.UNSETTLED
    assert completion.scope_error is not None
    assert transport.publications == []
    await application.close()


@pytest.mark.asyncio
async def test_reply_publication_uncertainty_is_not_reported_as_handler_retry() -> None:
    @controller()
    class Controller:
        @rpc("uncertain")
        async def uncertain(self, payload: Annotated[object, Payload()]) -> object:
            return payload

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    transport = RecordingTransport()
    transport.publish_error = TransportIndeterminateError("confirm lost")
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    now = datetime.now(UTC)
    request = RpcRequestEnvelope(
        uuid4(), SERVICE, "uncertain", 1, now, now + timedelta(seconds=1), uuid4()
    )

    with pytest.raises(TransportIndeterminateError):
        await runtime._dispatch_message(
            encoded_request_delivery(MsgspecJsonMessageCodec(), request)
        )
    await application.close()


@pytest.mark.asyncio
async def test_event_delivery_dispatches_by_exact_subscription_identity() -> None:
    calls: list[str] = []
    source = ServiceIdentity("kinker", "profiles", 1)

    @controller()
    class Controller:
        @event_handler(
            source,
            "changed",
            schema_version=1,
            mode=EventDispatchMode.BROADCAST,
            subscription="first",
            reliable=True,
        )
        async def first(self, payload: Annotated[object, Payload()]) -> None:
            calls.append("first")

        @event_handler(
            source,
            "changed",
            schema_version=1,
            mode=EventDispatchMode.BROADCAST,
            subscription="second",
            reliable=True,
        )
        async def second(self, payload: Annotated[object, Payload()]) -> None:
            calls.append("second")

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    transport = RecordingTransport()
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            options=MicroservicesOptions(instance_id="replica-a"),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    codec = MsgspecJsonMessageCodec()
    event = EventEnvelope(
        uuid4(), source, "changed", 1, datetime.now(UTC), payload={"value": 1}
    )
    identity = EventIdentity(source, "changed", 1)

    assert len(transport.subscriptions) == 2
    assert all(item.reliable for item in transport.subscriptions)
    for subscription in reversed(transport.subscriptions):
        completion = await runtime._dispatch_message(
            EncodedDelivery(
                event.message_id,
                identity.routing_key,
                codec.encode_event(event),
                {},
                datetime.now(UTC),
                subscription=subscription,
            )
        )
        assert completion.succeeded

    assert calls == ["second", "first"]
    await application.close()


@pytest.mark.asyncio
async def test_rpc_and_event_pipeline_contexts_receive_delivery_metadata() -> None:
    seen: list[MessageContext] = []

    class MetadataGuard:
        async def can_activate(self, context) -> bool:
            seen.append(context)
            return True

    class MetadataInterceptor:
        async def intercept(self, context, next):
            seen.append(context)
            return await next()

    guard = MetadataGuard()
    interceptor = MetadataInterceptor()
    source = ServiceIdentity("kinker", "profiles", 1)

    @controller()
    class Controller:
        @rpc("inspect")
        @use_guard(guard)
        @use_interceptor(interceptor)
        async def inspect(self, payload: Annotated[object, Payload()]) -> object:
            return payload

        @event_handler(
            source,
            "inspected",
            schema_version=1,
            mode=EventDispatchMode.SERVICE_POOL,
            subscription="metadata",
        )
        @use_guard(guard)
        @use_interceptor(interceptor)
        async def inspected(self, payload: Annotated[object, Payload()]) -> None:
            return None

    @module(controllers=[Controller])
    class ApplicationModule:
        pass

    limits = MessageLimits(max_header_bytes=8_000)
    transport = RecordingTransport()
    application = await TestingModule.create(
        MicroservicesModule.for_root(
            SERVICE,
            transport=RecordingFactory(transport),
            options=MicroservicesOptions(message_limits=limits),
            imports=(ApplicationModule,),
        )
    ).compile()
    runtime = cast(ServiceRuntime, await application.resolve(ServiceRuntime))
    codec = MsgspecJsonMessageCodec(limits)
    received_at = datetime.now(UTC)
    expires_at = received_at + timedelta(seconds=5)
    request = RpcRequestEnvelope(
        uuid4(),
        SERVICE,
        "inspect",
        1,
        received_at,
        expires_at,
        uuid4(),
        payload={"kind": "rpc"},
    )
    rpc_delivery = encoded_request_delivery(codec, request)
    rpc_delivery = EncodedDelivery(
        rpc_delivery.message_id,
        rpc_delivery.routing_key,
        rpc_delivery.body,
        rpc_delivery.headers,
        received_at,
        attempt=3,
        redelivered=True,
        correlation_id=rpc_delivery.correlation_id,
        reply_to=rpc_delivery.reply_to,
        expires_at=expires_at,
    )
    rpc_completion = await runtime._dispatch_message(rpc_delivery)
    assert rpc_completion.succeeded

    event = EventEnvelope(
        uuid4(),
        source,
        "inspected",
        1,
        received_at,
        payload={"kind": "event"},
    )
    subscription = transport.subscriptions[0]
    event_completion = await runtime._dispatch_message(
        EncodedDelivery(
            event.message_id,
            subscription.identity.routing_key,
            codec.encode_event(event),
            {},
            received_at,
            attempt=4,
            redelivered=True,
            expires_at=expires_at,
            subscription=subscription,
        )
    )
    assert event_completion.succeeded

    assert len(seen) == 4
    assert {context.execution_kind for context in seen} == {"rpc", "event"}
    assert any(isinstance(context, RpcContext) for context in seen)
    assert any(isinstance(context, EventContext) for context in seen)
    assert all(context.received_at == received_at for context in seen)
    assert all(context.expires_at == expires_at for context in seen)
    assert all(context.redelivered is True for context in seen)
    assert {context.attempt for context in seen} == {3, 4}
    assert all(context.limits == limits for context in seen)
    await application.close()
