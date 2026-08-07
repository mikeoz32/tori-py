"""Smoke-test nestpy-microservices wheel and source distributions."""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

PACKAGE_MODULES = (
    "__init__.py",
    "clients.py",
    "cluster.py",
    "codec.py",
    "compiler.py",
    "contexts.py",
    "decorators.py",
    "errors.py",
    "events.py",
    "identities.py",
    "inmemory.py",
    "invocation.py",
    "module.py",
    "options.py",
    "plans.py",
    "py.typed",
    "runtime.py",
    "testing.py",
    "transport.py",
    "wire.py",
)
RABBITMQ_MODULES = (
    "__init__.py",
    "client.py",
    "connection.py",
    "dependencies.py",
    "module.py",
    "options.py",
    "publisher.py",
    "server.py",
    "topology.py",
)


def _wheel_inventory() -> set[str]:
    package = {f"nestpy_microservices/{name}" for name in PACKAGE_MODULES}
    package.update(f"nestpy_microservices/rabbitmq/{name}" for name in RABBITMQ_MODULES)
    return {
        "nestpy_microservices/",
        "nestpy_microservices/rabbitmq/",
        *package,
        "nestpy_microservices-0.1.0.dist-info/",
        "nestpy_microservices-0.1.0.dist-info/METADATA",
        "nestpy_microservices-0.1.0.dist-info/RECORD",
        "nestpy_microservices-0.1.0.dist-info/WHEEL",
    }


def _sdist_inventory() -> set[str]:
    root = "nestpy_microservices-0.1.0"
    package = {f"{root}/src/nestpy_microservices/{name}" for name in PACKAGE_MODULES}
    package.update(
        f"{root}/src/nestpy_microservices/rabbitmq/{name}" for name in RABBITMQ_MODULES
    )
    return {
        root,
        f"{root}/PKG-INFO",
        f"{root}/README.md",
        f"{root}/pyproject.toml",
        f"{root}/src",
        f"{root}/src/nestpy_microservices",
        f"{root}/src/nestpy_microservices/rabbitmq",
        *package,
    }


def _assert_inventory(artifact: Path, expected: set[str]) -> None:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            actual = set(archive.namelist())
    else:
        with tarfile.open(artifact) as archive:
            actual = set(archive.getnames())
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise SystemExit(
            f"unexpected {artifact.name} inventory; missing={missing}, extra={extra}"
        )


def _read_metadata(artifact: Path) -> bytes:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            return archive.read("nestpy_microservices-0.1.0.dist-info/METADATA")
    with tarfile.open(artifact) as archive:
        member = archive.extractfile("nestpy_microservices-0.1.0/PKG-INFO")
        if member is None:
            raise SystemExit(f"missing metadata in {artifact.name}")
        return member.read()


def _assert_metadata(artifact: Path) -> None:
    metadata = BytesParser(policy=policy.compat32).parsebytes(_read_metadata(artifact))
    assert metadata["Name"] == "nestpy-microservices"
    assert metadata["Version"] == "0.1.0"
    assert metadata["Requires-Python"] == ">=3.14, <3.15"
    assert metadata.get_all("Requires-Dist") == [
        "msgspec>=0.19.0",
        "nestpy",
        "aio-pika>=10,<11 ; extra == 'rabbitmq'",
    ]
    assert metadata.get_all("Provides-Extra") == ["rabbitmq"]


def _assert_artifact_contract(wheel: Path, sdist: Path) -> None:
    _assert_inventory(wheel, _wheel_inventory())
    _assert_inventory(sdist, _sdist_inventory())
    _assert_metadata(wheel)
    _assert_metadata(sdist)


SMOKE = r"""
import sys

import nestpy_microservices
import nestpy_microservices.rabbitmq as rabbitmq

assert set(nestpy_microservices.__all__) == {
    "EventEnvelope",
    "EventDispatcher",
    "EventIdentity",
    "EventDispatchMode",
    "EventContext",
    "EventHandlerMetadata",
    "EventHandlerPlan",
    "EncodedDelivery",
    "ClientTransport",
    "ClientTransportFactory",
    "ClientClusterRoot",
    "ClientsModule",
    "ServiceCluster",
    "ServiceClusterOptions",
    "ServiceProxy",
    "DeliveryDispatcher",
    "IdentityValidationError",
    "Context",
    "HandlerCompilationError",
    "DuplicateSettlementError",
    "EventSubscription",
    "KeyedTransportFactoryReference",
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
    "PublicRpcError",
    "RESULT_MISSING",
    "RemoteRpcErrorData",
    "ReplyRoute",
    "RpcRequestEnvelope",
    "RpcResponseEnvelope",
    "RpcHandlerPlan",
    "RpcMetadata",
    "RpcContext",
    "RpcTarget",
    "ServiceIdentity",
    "ServiceHandlerRegistry",
    "ServerTransportFactory",
    "ServiceRuntime",
    "SettlementRecommendation",
    "Publication",
    "PublicationReceipt",
    "ReplyProtocolFailure",
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
    "UnknownServiceError",
    "RabbitMqModule",
    "RabbitMqChannelRole",
    "RabbitMqConnectionManager",
    "RabbitMqConnectionError",
    "RabbitMqClientTransport",
    "RabbitMqClientTransportFactory",
    "RabbitMqDeliveryMetadata",
    "RabbitMqError",
    "RabbitMqPublisher",
    "RabbitMqServerTransport",
    "RabbitMqServerTransportFactory",
    "BindingDeclaration",
    "ExchangeDeclaration",
    "RabbitMqOptions",
    "RabbitMqRoot",
    "RabbitMqTopology",
    "RabbitMqTransport",
    "RabbitMqStatus",
    "RabbitMqTopologyError",
    "QueueDeclaration",
    "rabbitmq_client_factory_token",
    "rabbitmq_manager_token",
    "rabbitmq_root_token",
    "rabbitmq_server_factory_token",
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
assert all(hasattr(nestpy_microservices, name) for name in nestpy_microservices.__all__)
assert set(rabbitmq.__all__) == {
    "BindingDeclaration",
    "RabbitMqChannelRole",
    "RabbitMqClientTransport",
    "RabbitMqClientTransportFactory",
    "RabbitMqChannels",
    "RabbitMqConnectionManager",
    "ExchangeDeclaration",
    "QueueDeclaration",
    "RabbitMqConnectionError",
    "RabbitMqDeliveryMetadata",
    "RabbitMqError",
    "RabbitMqModule",
    "RabbitMqOptions",
    "RabbitMqPublisher",
    "RabbitMqServerTransport",
    "RabbitMqServerTransportFactory",
    "RabbitMqRoot",
    "RabbitMqTopology",
    "RabbitMqTransport",
    "RabbitMqStatus",
    "RabbitMqTopologyError",
    "compile_event_topology",
    "compile_reply_topology",
    "compile_rpc_topology",
    "event_exchange_topology",
    "merge_topologies",
    "rabbitmq_client_factory_token",
    "rabbitmq_manager_token",
    "rabbitmq_root_token",
    "rabbitmq_server_factory_token",
    "require_aio_pika",
}
assert all(hasattr(rabbitmq, name) for name in rabbitmq.__all__)
assert "aio_pika" not in sys.modules
assert "starlette" not in sys.modules
assert "sqlalchemy" not in sys.modules
"""

RABBITMQ_SMOKE = r"""
import asyncio
import os
from uuid import uuid4

from nestpy_microservices import (
    EncodedDelivery,
    Publication,
    RabbitMqClientTransport,
    RabbitMqConnectionManager,
    RabbitMqOptions,
    RabbitMqServerTransport,
    RpcResponseEnvelope,
    ServiceCluster,
    ServiceIdentity,
    SettlementRecommendation,
    MsgspecJsonMessageCodec,
    utc_now,
)


async def main() -> None:
    service = ServiceIdentity("artifact", "smoke", 1)
    manager = RabbitMqConnectionManager(
        RabbitMqOptions(
            os.environ["RABBITMQ_URL"],
            connection_name="nestpy-microservices-artifact-smoke",
        )
    )
    server = RabbitMqServerTransport(manager, service)
    client = RabbitMqClientTransport(manager)
    cluster = ServiceCluster(client, manage_transport=True)
    codec = MsgspecJsonMessageCodec()

    async def dispatch(delivery: EncodedDelivery) -> SettlementRecommendation:
        request = codec.decode_request(delivery.body)
        response = RpcResponseEnvelope(
            message_id=uuid4(),
            correlation_id=request.correlation_id,
            completed_at=utc_now(),
            result=str(request.payload),
        )
        await server.publish_reply(
            Publication(
                message_id=response.message_id,
                routing_key=request.reply_to.value,
                body=codec.encode_response(response),
                headers={},
                mandatory=True,
                correlation_id=request.correlation_id,
            )
        )
        return SettlementRecommendation.ACK

    try:
        await manager.start()
        await server.prepare(rpc_methods=("ping",))
        await server.start(dispatch)
        await client.start()
        result = await cluster.service(service).request(
            "ping",
            "artifact",
            response_type=str,
            timeout=10,
        )
        assert result == "artifact"
    finally:
        await cluster.close()
        await server.close()
        await manager.close()


asyncio.run(main())
"""


def _one(dist: Path, pattern: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(
            f"expected one {pattern} artifact in {dist}, found {len(matches)}"
        )
    return matches[0]


def main() -> None:
    if len(sys.argv) not in {2, 3}:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR [RABBITMQ_URL]")
    dist = Path(sys.argv[1]).resolve()
    artifact_sets = (
        (
            _one(dist, "nestpy-0.1.0-*.whl"),
            _one(dist, "nestpy_microservices-*.whl"),
        ),
        (
            _one(dist, "nestpy-0.1.0.tar.gz"),
            _one(dist, "nestpy_microservices-*.tar.gz"),
        ),
    )
    _assert_artifact_contract(artifact_sets[0][1], artifact_sets[1][1])
    for artifacts in artifact_sets:
        command = ["uv", "run", "--isolated", "--no-project"]
        for artifact in artifacts:
            command.extend(("--with", str(artifact)))
        command.extend(("python", "-c", SMOKE))
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifacts[-1].name}")
        if len(sys.argv) == 3:
            rabbitmq = artifacts[1]
            requirement = (
                f"nestpy-microservices[rabbitmq] @ {rabbitmq.resolve().as_uri()}"
            )
            command = [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--with",
                str(artifacts[0]),
                "--with",
                requirement,
                "python",
                "-c",
                RABBITMQ_SMOKE,
            ]
            environment = os.environ.copy()
            environment["RABBITMQ_URL"] = sys.argv[2]
            completed = subprocess.run(
                command,
                check=False,
                text=True,
                env=environment,
            )
            if completed.returncode:
                raise SystemExit(f"RabbitMQ artifact smoke failed: {rabbitmq.name}")


if __name__ == "__main__":
    main()
