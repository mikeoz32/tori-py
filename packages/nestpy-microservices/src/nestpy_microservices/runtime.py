"""Application lifecycle participant for one microservices service root."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol
from uuid import uuid4

from nestpy import DiscoveryService, ModulesContainer, ShutdownContext, WorkScopeFactory

from nestpy_microservices.codec import MessageCodec, MsgspecJsonMessageCodec
from nestpy_microservices.compiler import compile_discovered_service_handlers
from nestpy_microservices.errors import TransportStateError
from nestpy_microservices.identities import ServiceIdentity, utc_now
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
    TransportStatus,
)
from nestpy_microservices.wire import RemoteRpcErrorData, RpcResponseEnvelope


class ServerTransportFactory(Protocol):
    """Create one server transport without opening native resources."""

    def create(
        self, identity: ServiceIdentity, options: MicroservicesOptions
    ) -> ServerTransport: ...


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
                )
                for plan in registry.event_handlers
            )
            try:
                await transport.prepare(
                    rpc_methods=tuple(plan.method for plan in registry.rpc_handlers),
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
        if delivery.routing_key.startswith(f"{self.identity.label}."):
            envelope = self._codec.decode_request(delivery.body)
            plan = next(
                (
                    candidate
                    for candidate in registry.rpc_handlers
                    if candidate.method == envelope.method
                ),
                None,
            )
            if plan is None:
                raise TransportStateError(
                    f"RPC method {envelope.method!r} is not registered"
                )
            invocation = MessageInvocation(
                application_id=self.identity.label,
                message_id=envelope.message_id,
                correlation_id=envelope.correlation_id,
                payload=envelope.payload,
                headers=envelope.headers,
                metadata={"routing_key": delivery.routing_key, "kind": envelope.kind},
                native=delivery.native,
            )
            completion = await self._executor.invoke(
                work_scopes,
                plan,
                invocation,
                encode_result=lambda value: value,
            )
            error = completion.body_error or completion.scope_error
            if error is None:
                response = RpcResponseEnvelope(
                    message_id=uuid4(),
                    correlation_id=envelope.correlation_id,
                    completed_at=utc_now(),
                    result=completion.result,
                )
            else:
                response = RpcResponseEnvelope(
                    message_id=uuid4(),
                    correlation_id=envelope.correlation_id,
                    completed_at=utc_now(),
                    error=RemoteRpcErrorData(
                        code=getattr(error, "diagnostic_code", "microservices.error"),
                        message=str(error)[:4096] or type(error).__name__,
                        retryable=(
                            completion.recommendation is SettlementRecommendation.RETRY
                        ),
                    ),
                )
            await transport.publish_reply(
                Publication(
                    message_id=response.message_id,
                    routing_key=envelope.reply_to.value,
                    body=self._codec.encode_response(response),
                    headers={},
                    mandatory=True,
                    correlation_id=envelope.correlation_id,
                )
            )
            return completion

        envelope = self._codec.decode_event(delivery.body)
        plan = next(
            (
                candidate
                for candidate in registry.event_handlers
                if candidate.identity.source == envelope.source
                and candidate.identity.event == envelope.event
                and candidate.identity.schema_version == envelope.schema_version
            ),
            None,
        )
        if plan is None:
            raise TransportStateError(f"event {envelope.event!r} is not registered")
        invocation = MessageInvocation(
            application_id=self.identity.label,
            message_id=envelope.message_id,
            correlation_id=envelope.correlation_id,
            payload=envelope.payload,
            headers=envelope.headers,
            metadata={"routing_key": delivery.routing_key, "kind": envelope.kind},
            native=delivery.native,
        )
        return await self._executor.invoke(
            work_scopes,
            plan,
            invocation,
            encode_result=lambda value: value,
        )

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


__all__ = ["ServerTransportFactory", "ServiceRuntime"]
