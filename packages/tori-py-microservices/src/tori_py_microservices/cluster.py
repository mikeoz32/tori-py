"""Bounded asynchronous client cluster and shared reply router."""

from __future__ import annotations

import asyncio
import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, TypeVar
from uuid import UUID, uuid4

import msgspec

from tori_py_microservices.codec import MessageCodec, MsgspecJsonMessageCodec
from tori_py_microservices.errors import (
    RemoteRpcError,
    RpcOutcomeUnknownError,
    RpcProtocolError,
    RpcTimeoutError,
    TransportCapacityError,
    TransportError,
    TransportStateError,
    TransportTimeoutError,
    TransportUnroutableError,
    UnknownServiceError,
)
from tori_py_microservices.identities import (
    MessageLimits,
    ReplyRoute,
    RpcTarget,
    ServiceIdentity,
    utc_now,
    validate_alias,
)
from tori_py_microservices.transport import (
    ClientTransport,
    Publication,
    ReplyProtocolFailure,
    TransportStatus,
)
from tori_py_microservices.wire import (
    RpcRequestEnvelope,
    RpcResponseEnvelope,
    freeze_headers,
)

ResponseT = TypeVar("ResponseT")


@dataclass(frozen=True, slots=True)
class ServiceClusterOptions:
    """Finite defaults and bounds for one shared client reply router."""

    default_rpc_timeout: float = 5.0
    max_rpc_timeout: float = 30.0
    max_pending_requests: int = 1024
    message_limits: MessageLimits = field(default_factory=MessageLimits)
    default_namespace: str | None = None
    default_contract_version: int | None = None
    max_cached_proxies: int = 1024

    def __post_init__(self) -> None:
        for name in ("default_rpc_timeout", "max_rpc_timeout"):
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        if self.default_rpc_timeout > self.max_rpc_timeout:
            raise ValueError("default_rpc_timeout cannot exceed max_rpc_timeout")
        if not isinstance(self.max_pending_requests, int) or (
            isinstance(self.max_pending_requests, bool)
            or self.max_pending_requests <= 0
        ):
            raise ValueError("max_pending_requests must be positive")
        if not isinstance(self.max_cached_proxies, int) or (
            isinstance(self.max_cached_proxies, bool) or self.max_cached_proxies <= 0
        ):
            raise ValueError("max_cached_proxies must be positive")
        if not isinstance(self.message_limits, MessageLimits):
            raise TypeError("message_limits must be MessageLimits")
        if self.default_namespace is not None:
            validate_alias(self.default_namespace, "default_namespace")
        if self.default_contract_version is not None and (
            not isinstance(self.default_contract_version, int)
            or isinstance(self.default_contract_version, bool)
            or self.default_contract_version <= 0
        ):
            raise ValueError("default_contract_version must be positive")


@dataclass(frozen=True, slots=True)
class ServiceProxy:
    """Immutable cached view of one complete target service identity."""

    cluster: ServiceCluster
    identity: ServiceIdentity

    async def request(
        self,
        method: str,
        payload: object,
        *,
        response_type: type[ResponseT],
        schema_version: int = 1,
        timeout: float | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
        headers: Mapping[str, object] | None = None,
    ) -> ResponseT:
        return await self.cluster.request(
            self.identity,
            method,
            payload,
            response_type=response_type,
            schema_version=schema_version,
            timeout=timeout,
            correlation_id=correlation_id,
            causation_id=causation_id,
            headers=headers,
        )


class ServiceCluster:
    """One shared client transport and reply consumer for many service proxies."""

    def __init__(
        self,
        transport: ClientTransport,
        *,
        options: ServiceClusterOptions | None = None,
        codec: MessageCodec | None = None,
        manage_transport: bool = False,
    ) -> None:
        self.options = ServiceClusterOptions() if options is None else options
        self.transport = transport
        self.codec = codec or MsgspecJsonMessageCodec(self.options.message_limits)
        self.manage_transport = manage_transport
        self._proxies: OrderedDict[ServiceIdentity, ServiceProxy] = OrderedDict()
        self._pending: dict[UUID, asyncio.Future[RpcResponseEnvelope]] = {}
        self._pending_generations: dict[UUID, int] = {}
        self._start_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._router_task: asyncio.Task[None] | None = None
        self._router_reply_to: ReplyRoute | None = None
        self._router_generation: int | None = None
        self._transport_generation_value = 0
        self._status_task: asyncio.Task[None] | None = None
        self._route_ready = asyncio.Event()
        self._closed = False
        self._close_complete = False

    def service(
        self,
        identity_or_name: ServiceIdentity | str,
        *,
        version: int | None = None,
    ) -> ServiceProxy:
        if isinstance(identity_or_name, ServiceIdentity):
            identity = identity_or_name
        else:
            namespace = self.options.default_namespace
            contract_version = (
                version
                if version is not None
                else self.options.default_contract_version
            )
            if namespace is None:
                raise ValueError("a default namespace is required for string services")
            if contract_version is None:
                raise ValueError("a contract version is required for string services")
            identity = ServiceIdentity(namespace, identity_or_name, contract_version)
        proxy = self._proxies.get(identity)
        if proxy is None:
            if len(self._proxies) >= self.options.max_cached_proxies:
                self._proxies.popitem(last=False)
            proxy = ServiceProxy(self, identity)
            self._proxies[identity] = proxy
        else:
            self._proxies.move_to_end(identity)
        return proxy

    def __getitem__(self, name: str) -> ServiceProxy:
        if self.options.default_contract_version is None:
            raise ValueError("a default contract version is required for indexing")
        return self.service(name)

    async def start(self) -> None:
        while True:
            wait_for_route = False
            stale_router: asyncio.Task[None] | None = None
            async with self._start_lock:
                if self._closed:
                    raise TransportStateError("service cluster is closed")
                if self.transport.status is TransportStatus.CREATED:
                    await self.transport.start()
                elif self.transport.status is TransportStatus.CLOSED:
                    raise TransportStateError("client transport is closed")
                if self._status_task is None or self._status_task.done():
                    self._status_task = asyncio.create_task(
                        self._watch_transport_status()
                    )
                if self.transport.status is not TransportStatus.RUNNING:
                    self._route_ready.clear()
                    wait_for_route = True
                elif not self._route_ready.is_set():
                    wait_for_route = True
                elif self._router_task is not None and (
                    not self._router_task.done()
                    and (
                        self._router_reply_to != self.transport.reply_to
                        or self._router_generation != self._transport_generation()
                    )
                ):
                    stale_router = self._router_task
                else:
                    if self._router_task is None or self._router_task.done():
                        generation = self._transport_generation()
                        self._router_task = asyncio.create_task(
                            self._route_replies(generation)
                        )
                        self._router_reply_to = self.transport.reply_to
                        self._router_generation = generation
                    self._route_ready.set()
                    return
            if stale_router is not None:
                await asyncio.gather(stale_router, return_exceptions=True)
            elif wait_for_route:
                while True:
                    if self._closed:
                        raise TransportStateError("service cluster is closed")
                    if self.transport.status is TransportStatus.CLOSED:
                        raise TransportStateError("client transport is closed")
                    if (
                        self.transport.status is TransportStatus.RUNNING
                        and self._route_ready.is_set()
                    ):
                        break
                    try:
                        await asyncio.wait_for(self._route_ready.wait(), timeout=0.1)
                    except TimeoutError:
                        continue

    async def request(
        self,
        identity: ServiceIdentity,
        method: str,
        payload: object,
        *,
        response_type: type[ResponseT],
        schema_version: int = 1,
        timeout: float | None = None,
        correlation_id: UUID | None = None,
        causation_id: UUID | None = None,
        headers: Mapping[str, object] | None = None,
    ) -> ResponseT:
        async with self._lifecycle_lock:
            if self._closed:
                raise TransportStateError("service cluster is closed")
        selected_timeout = (
            self.options.default_rpc_timeout if timeout is None else timeout
        )
        if (
            not isinstance(selected_timeout, (int, float))
            or isinstance(selected_timeout, bool)
            or not math.isfinite(selected_timeout)
            or selected_timeout <= 0
            or selected_timeout > self.options.max_rpc_timeout
        ):
            raise ValueError(
                "timeout must be finite, positive, and within the client maximum"
            )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + selected_timeout
        created_at = utc_now()
        try:
            await asyncio.wait_for(self.start(), timeout=selected_timeout)
        except TimeoutError as error:
            raise RpcTimeoutError(
                "RPC transport was not ready before the deadline"
            ) from error
        async with self._lifecycle_lock:
            if self._closed:
                raise TransportStateError("service cluster is closed")
            if len(self._pending) >= self.options.max_pending_requests:
                raise TransportCapacityError("pending request map is full")
            correlation = correlation_id or uuid4()
            if correlation in self._pending:
                raise ValueError("correlation_id is already pending")
            future: asyncio.Future[RpcResponseEnvelope] = (
                asyncio.get_running_loop().create_future()
            )
            self._pending[correlation] = future
            self._pending_generations[correlation] = self._transport_generation()
        publish_task: asyncio.Task[object] | None = None
        response_task: asyncio.Task[RpcResponseEnvelope] | None = None
        try:
            deadline_at = created_at + timedelta(seconds=selected_timeout)
            request = RpcRequestEnvelope(
                message_id=uuid4(),
                service=identity,
                method=method,
                schema_version=schema_version,
                created_at=created_at,
                deadline_at=deadline_at,
                correlation_id=correlation,
                causation_id=causation_id,
                reply_to=self.transport.reply_to,
                headers=freeze_headers(headers, self.options.message_limits),
                payload=payload,
            )
            target = RpcTarget(identity, method, schema_version)
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TimeoutError
            publish_task = asyncio.create_task(
                self.transport.publish_rpc(
                    target,
                    Publication(
                        message_id=request.message_id,
                        routing_key=target.routing_key,
                        body=self.codec.encode_request(request),
                        headers={},
                        mandatory=True,
                        correlation_id=correlation,
                        reply_to=self.transport.reply_to,
                        expires_at=deadline_at,
                    ),
                )
            )

            async def wait_response() -> RpcResponseEnvelope:
                return await asyncio.shield(future)

            response_task = asyncio.create_task(wait_response())
            done, _ = await asyncio.wait(
                (publish_task, response_task),
                timeout=remaining,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                cancellation_error = await _cancel_task(publish_task)
                if isinstance(cancellation_error, TransportTimeoutError):
                    raise TimeoutError from cancellation_error
                raise RpcOutcomeUnknownError("RPC publication outcome is indeterminate")
            if response_task in done:
                response = response_task.result()
                self.transport.cancel_publication_after_reply(correlation)
                await _cancel_task(publish_task)
            else:
                await publish_task
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError
                response = await asyncio.wait_for(
                    asyncio.shield(future), timeout=remaining
                )
        except TimeoutError as error:
            await self._cleanup_request(correlation, publish_task, response_task)
            raise RpcTimeoutError("RPC request timed out") from error
        except RpcOutcomeUnknownError:
            await self._cleanup_request(correlation, publish_task, response_task)
            raise
        except asyncio.CancelledError:
            await self._cleanup_request(correlation, publish_task, response_task)
            raise
        except TransportUnroutableError as error:
            await self._cleanup_request(correlation, publish_task, response_task)
            raise UnknownServiceError(
                "the requested service or contract version is unavailable"
            ) from error
        except TransportError:
            await self._cleanup_request(correlation, publish_task, response_task)
            raise
        except Exception:
            await self._cleanup_request(correlation, publish_task, response_task)
            raise
        result = response.result
        if response.error is not None:
            raise RemoteRpcError(
                response.error.code,
                response.error.message,
                retryable=response.error.retryable,
                details=dict(response.error.details),
            )
        try:
            return msgspec.convert(result, type=response_type)
        except (TypeError, ValueError, msgspec.ValidationError) as error:
            raise RpcProtocolError("RPC result does not match response_type") from error

    async def close(self) -> None:
        async with self._start_lock:
            if self._close_complete:
                return
            self._closed = True
            self._route_ready.set()
            error = RpcOutcomeUnknownError(
                "service cluster closed with pending requests"
            )
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            for correlation in self._pending:
                self.transport.cancel_pending(correlation)
            self._pending.clear()
            self._pending_generations.clear()
            transport_error: BaseException | None = None
            if self.manage_transport:
                try:
                    await self.transport.close()
                except BaseException as error:
                    transport_error = error
            router = self._router_task
            if router is not None:
                if self.manage_transport and transport_error is None:
                    await asyncio.gather(router, return_exceptions=True)
                else:
                    router.cancel()
                    await asyncio.gather(router, return_exceptions=True)
            self._router_reply_to = None
            self._router_generation = None
            status_task = self._status_task
            self._status_task = None
            if status_task is not None and status_task is not asyncio.current_task():
                status_task.cancel()
                await asyncio.gather(status_task, return_exceptions=True)
            self._close_complete = True
            if transport_error is not None:
                raise transport_error

    async def on_application_shutdown(self) -> None:
        await self.close()

    async def _route_replies(self, generation: int) -> None:
        try:
            async for delivery in self.transport.replies():
                correlation = delivery.correlation_id
                if correlation is None:
                    continue
                if self._pending_generations.get(correlation) != generation:
                    continue
                future = self._pending.pop(correlation, None)
                self._pending_generations.pop(correlation, None)
                if future is None:
                    continue
                if isinstance(delivery, ReplyProtocolFailure):
                    future.set_exception(RpcProtocolError(delivery.reason))
                    continue
                if delivery.routing_key != self.transport.reply_to.value:
                    future.set_exception(
                        RpcProtocolError("RPC reply route does not match")
                    )
                    continue
                try:
                    response = self.codec.decode_response(delivery.body)
                except Exception as error:
                    future.set_exception(RpcProtocolError("malformed RPC reply"))
                    del error
                else:
                    if response.correlation_id != correlation:
                        future.set_exception(
                            RpcProtocolError("RPC reply correlation does not match")
                        )
                    else:
                        future.set_result(response)
            self._fail_pending(
                RpcOutcomeUnknownError("reply transport closed"),
                generation=generation,
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._fail_pending(
                RpcOutcomeUnknownError("reply transport closed unexpectedly"),
                generation=generation,
            )
            del error

    async def _watch_transport_status(self) -> None:
        try:
            async for event in self.transport.statuses():
                self._transport_generation_value = event.generation
                if event.status is TransportStatus.QUIESCING:
                    self._route_ready.clear()
                    interrupted_generation = self._router_generation
                    self._router_reply_to = None
                    self._router_generation = None
                    self._fail_pending(
                        RpcOutcomeUnknownError("reply transport was interrupted"),
                        generation=interrupted_generation,
                    )
                    router = self._router_task
                    if router is not None and router is not asyncio.current_task():
                        await asyncio.gather(router, return_exceptions=True)
                    self._router_task = None
                elif event.status is TransportStatus.RUNNING:
                    async with self._start_lock:
                        if self._closed:
                            return
                        if self._router_task is None or self._router_task.done():
                            generation = self._transport_generation()
                            self._router_task = asyncio.create_task(
                                self._route_replies(generation)
                            )
                            self._router_reply_to = self.transport.reply_to
                            self._router_generation = generation
                        self._route_ready.set()
                elif event.status is TransportStatus.CLOSED:
                    self._route_ready.clear()
                    self._fail_pending(RpcOutcomeUnknownError("reply transport closed"))
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._route_ready.clear()
            self._fail_pending(
                RpcOutcomeUnknownError("reply transport status was unavailable")
            )
            del error

    def _fail_pending(self, error: Exception, *, generation: int | None = None) -> None:
        correlations = tuple(
            correlation
            for correlation, pending_generation in self._pending_generations.items()
            if generation is None or pending_generation == generation
        )
        for correlation in correlations:
            future = self._pending.pop(correlation, None)
            self._pending_generations.pop(correlation, None)
            self.transport.cancel_pending(correlation)
            if future is not None and not future.done():
                future.set_exception(error)

    async def _cleanup_request(
        self,
        correlation: UUID,
        publish_task: asyncio.Task[object] | None,
        response_task: asyncio.Task[RpcResponseEnvelope] | None,
    ) -> None:
        self._pending.pop(correlation, None)
        self._pending_generations.pop(correlation, None)
        self.transport.cancel_pending(correlation)
        await _cancel_task(publish_task)
        await _cancel_task(response_task)

    def _transport_generation(self) -> int:
        return self._transport_generation_value


async def _cancel_task(task: asyncio.Task[Any] | None) -> BaseException | None:
    if task is None:
        return None
    if not task.done():
        task.cancel()
    result = await asyncio.gather(task, return_exceptions=True)
    outcome = result[0] if result else None
    return outcome if isinstance(outcome, BaseException) else None


__all__ = ["ServiceCluster", "ServiceClusterOptions", "ServiceProxy"]
