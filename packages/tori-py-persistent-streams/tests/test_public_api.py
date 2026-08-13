from __future__ import annotations

import ast
import inspect
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import cast

import pytest
import tori_py_persistent_streams
from tori_py import BootstrapError, ModuleSpec, NestApplication, ValueProvider, module
from tori_py_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PublisherRegistration,
    StreamAdapterFactory,
    StreamBinding,
    StreamConfigurationError,
)
from tori_py_persistent_streams.errors import (
    StreamHandlerCompilationError,
    StreamInvocationError,
    StreamPublicationSaturatedError,
    StreamRuntimeError,
    ToriPyPersistentStreamsError,
)
from tori_py_persistent_streams.testing import (
    InMemoryPersistentStreamsModule,
    InMemoryStreamAdapterFactory,
)
from tori_py_persistent_streams_core import StreamDefinition


class Codec:
    def encode(self, payload: object) -> bytes:
        return str(payload).encode()

    def decode(self, payload: bytes, target: type[object]) -> object:
        return target(payload.decode())


class Key:
    def resolve(self, payload: object) -> bytes:
        return str(payload).encode()


def options() -> PersistentStreamsOptions:
    return PersistentStreamsOptions(
        bindings=(
            StreamBinding(
                "events",
                StreamDefinition("events-v1", 2),
                str,
                Codec(),
                Key(),
            ),
        )
    )


def test_root_facade_is_exact() -> None:
    assert set(tori_py_persistent_streams.__all__) == {
        "ConfiguredStreamPublisher",
        "ToriPyPersistentStreamsError",
        "PartitionKeyResolver",
        "PartitionStatus",
        "PersistentStreamsModule",
        "PersistentStreamsOptions",
        "PersistentStreamsRuntimeOptions",
        "PublishOutcome",
        "PublishReceipt",
        "PublisherRegistration",
        "PublishingIdSource",
        "StreamAdapterFactory",
        "StreamBinding",
        "StreamCodec",
        "StreamConfigurationError",
        "StreamContext",
        "StreamHandlerCompilationError",
        "StreamHandlerMetadata",
        "StreamHandlerPlan",
        "StreamHandlerRegistry",
        "StreamHeader",
        "StreamHeaders",
        "StreamInject",
        "StreamInvocationError",
        "StreamOffset",
        "StreamParameterPlan",
        "StreamPartition",
        "StreamPayload",
        "StreamPipelineExecutor",
        "StreamPipelinePlan",
        "StreamPublishMetadata",
        "StreamPublisher",
        "StreamPublicationSaturatedError",
        "StreamRecordContext",
        "StreamRuntime",
        "StreamRuntimeError",
        "StreamRuntimeState",
        "compile_controller_stream_handlers",
        "compile_discovered_stream_handlers",
        "stream_handler",
        "stream_publish",
        "stream_publisher_token",
    }
    assert all(
        hasattr(tori_py_persistent_streams, name)
        for name in tori_py_persistent_streams.__all__
    )


def test_public_integration_diagnostic_codes_are_exact() -> None:
    assert (
        ToriPyPersistentStreamsError.diagnostic_code
        == "tori_py_persistent_streams.error"
    )
    assert StreamConfigurationError.diagnostic_code == (
        "tori_py_persistent_streams.invalid_configuration"
    )
    assert StreamHandlerCompilationError.diagnostic_code == (
        "tori_py_persistent_streams.invalid_handler"
    )
    assert StreamInvocationError.diagnostic_code == (
        "tori_py_persistent_streams.invocation_failed"
    )
    assert (
        StreamRuntimeError.diagnostic_code
        == "tori_py_persistent_streams.runtime_failed"
    )
    assert StreamPublicationSaturatedError.diagnostic_code == (
        "tori_py_persistent_streams.publication_saturated"
    )


def test_package_metadata_and_import_boundary_are_exact() -> None:
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["requires-python"] == ">=3.14,<3.15"
    assert project["project"]["dependencies"] == [
        "tori-py>=0.1.0,<0.2.0",
        "tori-py-persistent-streams-core>=0.1.0,<0.2.0",
    ]
    assert (root / "README.md").is_file()
    assert (root / "scripts/verify_artifacts.py").is_file()
    assert (root / "src/tori_py_persistent_streams/py.typed").is_file()

    script = """
import sys
import tori_py_persistent_streams
forbidden = {
    'aio_pika', 'rstream', 'sqlalchemy', 'starlette',
    'tori_py_microservices', 'tori_py_cqrs', 'tori_py_cqrs_core',
}
assert forbidden.isdisjoint(sys.modules)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_root_is_global_and_imports_adapter() -> None:
    adapter = InMemoryPersistentStreamsModule.for_root()
    descriptor = PersistentStreamsModule.for_root(options(), imports=[adapter])
    spec = cast(ModuleSpec, descriptor.factory())

    assert spec.global_ is True
    assert tuple(spec.imports) == (adapter,)
    adapter_spec = cast(ModuleSpec, adapter.factory())
    assert tuple(adapter_spec.exports) == (StreamAdapterFactory,)
    assert "key" not in inspect.signature(PersistentStreamsModule.for_root).parameters
    assert (
        "global_" not in inspect.signature(PersistentStreamsModule.for_root).parameters
    )


@pytest.mark.asyncio
async def test_root_compiles_with_one_adapter_import() -> None:
    streams = PersistentStreamsModule.for_root(
        options(), imports=[InMemoryPersistentStreamsModule.for_root()]
    )

    @module(imports=[streams])
    class AppModule:
        pass

    application = await NestApplication.create(AppModule)
    await application.start()
    await application.shutdown()


@pytest.mark.asyncio
async def test_root_without_adapter_reports_unresolved_factory() -> None:
    @module(imports=[PersistentStreamsModule.for_root(options())])
    class AppModule:
        pass

    with pytest.raises(BootstrapError) as failure:
        await NestApplication.create(AppModule)
    assert failure.value.diagnostic_code == "provider.unresolved"


@pytest.mark.asyncio
async def test_root_with_two_adapter_modules_reports_ambiguous_factory() -> None:
    @module(
        providers=[ValueProvider(StreamAdapterFactory, InMemoryStreamAdapterFactory())],
        exports=[StreamAdapterFactory],
    )
    class OtherAdapterModule:
        pass

    streams = PersistentStreamsModule.for_root(
        options(),
        imports=[InMemoryPersistentStreamsModule.for_root(), OtherAdapterModule],
    )

    @module(imports=[streams])
    class AppModule:
        pass

    with pytest.raises(BootstrapError) as failure:
        await NestApplication.create(AppModule)
    assert failure.value.diagnostic_code == "provider.ambiguous"


def test_explicit_publisher_name_cannot_overwrite_implicit_binding_alias() -> None:
    with pytest.raises(StreamConfigurationError, match="collide"):
        PersistentStreamsOptions(
            options().bindings,
            publishers=(PublisherRegistration("events", name="events"),),
        )


def test_runtime_sources_have_no_forbidden_imports() -> None:
    package = Path(__file__).parents[1] / "src" / "tori_py_persistent_streams"
    forbidden = {
        "aio_pika",
        "rstream",
        "sqlalchemy",
        "starlette",
        "tori_py_microservices",
        "tori_py_cqrs",
    }
    imported: set[str] = set()
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden)


@pytest.mark.asyncio
async def test_two_distinct_roots_are_rejected_before_adapter_creation() -> None:
    adapter = InMemoryPersistentStreamsModule.for_root()

    @module(
        imports=[
            PersistentStreamsModule.for_root(options(), imports=[adapter]),
            PersistentStreamsModule.for_root(options(), imports=[adapter]),
        ]
    )
    class AppModule:
        pass

    with pytest.raises(BootstrapError, match="different deferred descriptors"):
        await NestApplication.create(AppModule)


@pytest.mark.asyncio
async def test_transitively_imported_duplicate_roots_are_rejected() -> None:
    adapter = InMemoryPersistentStreamsModule.for_root()

    @module(imports=[PersistentStreamsModule.for_root(options(), imports=[adapter])])
    class FirstFeature:
        pass

    @module(imports=[PersistentStreamsModule.for_root(options(), imports=[adapter])])
    class SecondFeature:
        pass

    @module(imports=[FirstFeature, SecondFeature])
    class AppModule:
        pass

    with pytest.raises(BootstrapError, match="different deferred descriptors"):
        await NestApplication.create(AppModule)
