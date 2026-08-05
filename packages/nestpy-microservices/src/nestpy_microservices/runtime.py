"""Application lifecycle participant for one microservices service root."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import replace
from uuid import UUID, uuid4

from nestpy import DiscoveryService, ModulesContainer, ShutdownContext, WorkScopeFactory

from nestpy_microservices.codec import MessageCodec, MsgspecJsonMessageCodec
from nestpy_microservices.compiler import compile_discovered_service_handlers
from nestpy_microservices.decorators import EventDispatchMode
from nestpy_microservices.errors import (
    MessageAuthorizationError,
    MessageRejectedError,
    MessageRetryableError,
    PublicRpcError,
    TransportStateError,
    TransportUnroutableError,
)
from nestpy_microservices.identities import (
    EventIdentity,
    MessageLimits,
    RpcTarget,
    ServiceIdentity,
    utc_now,
)
from nestpy_microservices.invocation import (
    InvocationCompletion,
    MessageInvocation,
    MessagePipelineExecutor,
    SettlementRecommendation,
)
from nestpy_microservices.options import MicroservicesOptions
from nestpy_microservices.plans import ServiceHandlerRegistry
from nestpy_microservices.transport import (
    DeliveryDispatcher,
    EncodedDelivery,
    EventSubscription,
    Publication,
    ServerTransport,
    ServerTransportFactory,
    TransportStatus,
)
from nestpy_microservices.wire import (
    RemoteRpcErrorData,
    RpcRequestEnvelope,
    RpcResponseEnvelope,
)


class ServiceRuntime:
    """Own one service transport, admission gate, and accepted delivery tasks."""

    def __init__(
        self,
        identity: ServiceIdentity,
        *,
        transport_factory: ServerTransportFactory,
        discovery: DiscoveryService,
        modules: ModulesContainer,
        work_scopes: WorkScopeFactory | None = None,
        options: MicroservicesOptions | None = None,
        dispatcher: DeliveryDispatcher | None = None,
        codec: MessageCodec | None = None,
    ) -> None:
        self.identity = identity
        self.options = options or MicroservicesOptions()
        self._transport_factory = transport_factory
        self._discovery = discovery
        self._modules = modules
        self._work_scopes = work_scopes
        self._dispatcher = dispatcher
        self._codec = codec or MsgspecJsonMessageCodec(self.options.message_limits)
        self._executor = MessagePipelineExecutor(self.options.global_pipeline)
        self._transport: ServerTransport | None = None
        self._registry: ServiceHandlerRegistry | None = None
        self._semaphore = asyncio.Semaphore(self.options.max_concurrency)
        self._tasks: set[asyncio.Task[object]] = set()
        self._accepting = False
        self._start_lock = asyncio.Lock()
        self._close_lock = asyncio.Lock()

    @property
    def transport(self) -> ServerTransport | None:
        return self._transport

    @property
    def registry(self) -> ServiceHandlerRegistry | None:
        return self._registry

    @property
    def accepting(self) -> bool:
        return self._accepting

    async def on_application_bootstrap(self) -> None:
        async with self._start_lock:
            if self._accepting:
                return
            registry = compile_discovered_service_handlers(
                self._discovery, modules=self._modules
            )
            transport = self._transport_factory.create(self.identity, self.options)
            if not isinstance(transport, ServerTransport):
                raise TransportStateError(
                    "transport factory did not create a ServerTransport"
                )
            self._transport = transport
            subscriptions = tuple(
                EventSubscription(
                    plan.identity,
                    plan.mode.value,
                    plan.subscription,
                    destination=self.identity,
                    instance_id=self.options.instance_id,
                    reliable=plan.metadata.reliable,
                )
                for plan in registry.event_handlers
            )
            try:
                await transport.prepare(
                    rpc_methods=registry.rpc_methods,
                    subscriptions=subscriptions,
                )
                self._registry = registry
                self._accepting = True
                await transport.start(self._receive)
            except BaseException:
                self._accepting = False
                try:
                    await transport.close()
                except BaseException:
                    pass
                self._transport = None
                raise
            if transport.status is not TransportStatus.RUNNING:
                self._accepting = False
                try:
                    await transport.close()
                except BaseException:
                    pass
                self._transport = None
                raise TransportStateError("transport did not become ready")

    async def on_application_quiesce(self, context: ShutdownContext) -> None:
        self._accepting = False
        transport = self._transport
        if transport is None:
            return
        await transport.stop_intake()
        await self._drain_tasks(context.remaining)

    async def close(self) -> None:
        async with self._close_lock:
            self._accepting = False
            transport = self._transport
            if transport is not None:
                await transport.close()
            self._transport = None

    async def on_application_shutdown(self) -> None:
        await self.close()

    async def _receive(
        self, delivery: EncodedDelivery
    ) -> InvocationCompletion | SettlementRecommendation:
        if not self._accepting:
            raise TransportStateError("delivery received outside service admission")
        dispatcher = self._dispatcher or self._dispatch_message
        task = asyncio.current_task()
        if task is not None:
            self._tasks.add(task)
        try:
            async with self._semaphore:
                return await dispatcher(delivery)
        finally:
            if task is not None:
                self._tasks.discard(task)

    async def _dispatch_message(
        self, delivery: EncodedDelivery
    ) -> InvocationCompletion:
        registry = self._registry
        work_scopes = self._work_scopes
        transport = self._transport
        if registry is None or work_scopes is None or transport is None:
            raise TransportStateError("service runtime is not fully initialized")
        if delivery.subscription is None:
            try:
                envelope = self._codec.decode_request(delivery.body)
            except Exception as error:
                return _terminal_rejection(error)
            target = RpcTarget(
                envelope.service, envelope.method, envelope.schema_version
            )
            if (
                envelope.service != self.identity
                or delivery.routing_key != target.routing_key
                or delivery.message_id != envelope.message_id
                or delivery.correlation_id != envelope.correlation_id
                or delivery.reply_to != envelope.reply_to
            ):
                return _terminal_rejection(
                    MessageRejectedError(
                        "RPC transport metadata does not match envelope"
                    )
                )
            now = utc_now()
            if delivery.expires_at is not None and delivery.expires_at <= now:
                return await self._publish_error_response(
                    transport,
                    envelope.correlation_id,
                    envelope.reply_to.value,
                    RemoteRpcErrorData(
                        "deadline_exceeded",
                        "The RPC deadline has elapsed.",
                        False,
                    ),
                )
            if envelope.deadline_at <= now:
                return await self._publish_error_response(
                    transport,
                    envelope.correlation_id,
                    envelope.reply_to.value,
                    RemoteRpcErrorData(
                        "deadline_exceeded",
                        "The RPC deadline has elapsed.",
                        False,
                    ),
                )
            duration = (envelope.deadline_at - envelope.created_at).total_seconds()
            if duration > self.options.max_accepted_rpc_timeout:
                return _terminal_rejection(
                    MessageRejectedError("RPC deadline exceeds the accepted duration")
                )
            plan = registry.rpc_by_target.get(
                (envelope.method, envelope.schema_version)
            )
            if plan is None:
                method_exists = envelope.method in registry.rpc_methods
                return await self._publish_error_response(
                    transport,
                    envelope.correlation_id,
                    envelope.reply_to.value,
                    RemoteRpcErrorData(
                        "unsupported_schema" if method_exists else "method_not_found",
                        (
                            "The RPC request schema is not supported."
                            if method_exists
                            else "The RPC method is not registered."
                        ),
                        False,
                    ),
                )
            invocation = _message_invocation(
                self.identity,
                delivery,
                envelope,
                self.options.message_limits,
            )
            response_id = uuid4()

            def encode_result(value: object) -> bytes:
                return self._codec.encode_response(
                    RpcResponseEnvelope(
                        message_id=response_id,
                        correlation_id=envelope.correlation_id,
                        completed_at=utc_now(),
                        result=value,
                    )
                )

            completion = await self._executor.invoke(
                work_scopes,
                plan,
                invocation,
                encode_result=encode_result,
            )
            if completion.scope_error is not None:
                return completion
            if completion.body_error is None:
                encoded_response = completion.encoded_response
                if not isinstance(encoded_response, bytes):
                    raise TransportStateError("RPC executor did not encode a response")
            else:
                encoded_response = self._codec.encode_response(
                    RpcResponseEnvelope(
                        message_id=response_id,
                        correlation_id=envelope.correlation_id,
                        completed_at=utc_now(),
                        error=_safe_remote_error(completion.body_error),
                    )
                )
            return await self._publish_completion(
                transport,
                completion,
                response_id=response_id,
                correlation_id=envelope.correlation_id,
                reply_to=envelope.reply_to.value,
                body=encoded_response,
            )

        subscription = delivery.subscription
        try:
            event = self._codec.decode_event(delivery.body)
            envelope_identity = EventIdentity(
                event.source, event.event, event.schema_version
            )
            mode = EventDispatchMode(subscription.mode)
        except Exception as error:
            return _terminal_rejection(error)
        if (
            envelope_identity != subscription.identity
            or delivery.routing_key != subscription.identity.routing_key
            or delivery.message_id != event.message_id
            or (
                delivery.correlation_id is not None
                and delivery.correlation_id != event.correlation_id
            )
        ):
            return _terminal_rejection(
                MessageRejectedError("event transport metadata does not match envelope")
            )
        plan = registry.event_by_subscription.get(
            (subscription.identity, mode, subscription.subscription)
        )
        if plan is None:
            return _terminal_rejection(
                MessageRejectedError("event subscription is not registered")
            )
        invocation = MessageInvocation(
            application_id=self.identity.label,
            message_id=event.message_id,
            correlation_id=event.correlation_id,
            payload=event.payload,
            headers=event.headers,
            metadata={"routing_key": delivery.routing_key, "kind": event.kind},
            received_at=delivery.received_at,
            expires_at=delivery.expires_at,
            attempt=delivery.attempt,
            redelivered=delivery.redelivered,
            native=delivery.native,
            limits=self.options.message_limits,
        )
        return await self._executor.invoke(
            work_scopes,
            plan,
            invocation,
            encode_result=lambda value: value,
        )

    async def _publish_error_response(
        self,
        transport: ServerTransport,
        correlation_id: UUID,
        reply_to: str,
        error: RemoteRpcErrorData,
    ) -> InvocationCompletion:
        response_id = uuid4()
        completion = InvocationCompletion(
            recommendation=SettlementRecommendation.REJECT,
            body_error=MessageRejectedError(error.code),
        )
        body = self._codec.encode_response(
            RpcResponseEnvelope(
                message_id=response_id,
                correlation_id=correlation_id,
                completed_at=utc_now(),
                error=error,
            )
        )
        return await self._publish_completion(
            transport,
            completion,
            response_id=response_id,
            correlation_id=correlation_id,
            reply_to=reply_to,
            body=body,
        )

    async def _publish_completion(
        self,
        transport: ServerTransport,
        completion: InvocationCompletion,
        *,
        response_id: UUID,
        correlation_id: UUID,
        reply_to: str,
        body: bytes,
    ) -> InvocationCompletion:
        publication = Publication(
            message_id=response_id,
            routing_key=reply_to,
            body=body,
            headers={},
            mandatory=True,
            correlation_id=correlation_id,
        )
        try:
            await transport.publish_reply(publication)
        except TransportUnroutableError:
            return replace(completion, recommendation=SettlementRecommendation.ACK)
        return replace(completion, recommendation=SettlementRecommendation.ACK)

    async def _drain_tasks(self, remaining: Callable[[], float | None]) -> None:
        while self._tasks:
            timeout = remaining()
            if timeout is not None and timeout <= 0:
                for task in tuple(self._tasks):
                    task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self._tasks, return_exceptions=True),
                        timeout=0.1,
                    )
                except TimeoutError:
                    pass
                return
            gather = asyncio.gather(*self._tasks, return_exceptions=True)
            try:
                if timeout is None:
                    await gather
                else:
                    await asyncio.wait_for(gather, timeout=timeout)
            except TimeoutError:
                for task in tuple(self._tasks):
                    task.cancel()
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*self._tasks, return_exceptions=True),
                        timeout=0.1,
                    )
                except TimeoutError:
                    pass
                return


def _message_invocation(
    identity: ServiceIdentity,
    delivery: EncodedDelivery,
    envelope: RpcRequestEnvelope,
    limits: MessageLimits,
) -> MessageInvocation:
    return MessageInvocation(
        application_id=identity.label,
        message_id=envelope.message_id,
        correlation_id=envelope.correlation_id,
        payload=envelope.payload,
        headers=envelope.headers,
        metadata={"routing_key": delivery.routing_key, "kind": envelope.kind},
        received_at=delivery.received_at,
        expires_at=delivery.expires_at,
        attempt=delivery.attempt,
        redelivered=delivery.redelivered,
        native=delivery.native,
        limits=limits,
    )


def _terminal_rejection(error: Exception) -> InvocationCompletion:
    return InvocationCompletion(
        recommendation=SettlementRecommendation.REJECT,
        body_error=error,
    )


def _safe_remote_error(error: Exception) -> RemoteRpcErrorData:
    if isinstance(error, PublicRpcError):
        try:
            return RemoteRpcErrorData(
                error.code,
                error.public_message,
                error.retryable,
                error.details,
            )
        except Exception:
            pass
    if isinstance(error, MessageAuthorizationError):
        return RemoteRpcErrorData(
            "authorization_failed",
            "The RPC request was not authorized.",
            False,
        )
    if isinstance(error, MessageRetryableError):
        return RemoteRpcErrorData(
            "temporarily_unavailable",
            "The RPC request could not be completed.",
            True,
        )
    if isinstance(error, MessageRejectedError):
        return RemoteRpcErrorData(
            "invalid_request",
            "The RPC request was rejected.",
            False,
        )
    return RemoteRpcErrorData(
        "internal_error",
        "The remote service could not complete the request.",
        False,
    )


__all__ = ["ServerTransportFactory", "ServiceRuntime"]
