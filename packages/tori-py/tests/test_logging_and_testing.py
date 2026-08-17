import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast

import pytest
from tori_py import (
    ApplicationStateError,
    ModuleSpec,
    NestApplication,
    ValueProvider,
    injectable,
    module,
)
from tori_py.core.errors import BootstrapError
from tori_py.core.modules import DeferredModule
from tori_py.core.protocols import Logger
from tori_py.logging import LoggingModule, PythonLogger, use_log_context
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule, http_client


def test_logger_preserves_reserved_framework_fields(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = PythonLogger(logging.getLogger("test-n3"), {"application": "app"})
    with use_log_context(request_id="request-1", module="framework-module"):
        with caplog.at_level(logging.INFO, logger="test-n3"):
            logger.bind(
                application="user",
                request_id="user",
                module="user-module",
                custom="value",
            ).info(
                "message",
                application="user",
                request_id="user",
                module="user-module",
            )
    fields = cast(dict[str, object], caplog.records[-1].__dict__["tori_py"])
    assert fields["application"] == "app"
    assert fields["request_id"] == "request-1"
    assert fields["module"] == "framework-module"
    assert fields["custom"] == "value"


@pytest.mark.asyncio
async def test_logging_module_is_global_and_resolves_through_visibility() -> None:
    logging_module = LoggingModule.for_root(application="test")

    @module(imports=[logging_module])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    logger = await application.resolve(Logger)
    assert isinstance(logger, PythonLogger)
    await application.close()


@pytest.mark.asyncio
async def test_testing_module_overrides_public_provider_and_seals() -> None:
    @module(
        providers=[
            ValueProvider("public", "original"),
            ValueProvider("private", "secret"),
        ],
        exports=["public"],
    )
    class Root:
        pass

    builder = TestingModule.create(Root)
    builder.override_provider("public", module=Root).use_value("replacement")
    application = await builder.compile()
    assert await application.resolve("public") == "replacement"
    with pytest.raises(BootstrapError, match="sealed"):
        builder.override_provider("public", module=Root)
    await application.close()

    private_builder = TestingModule.create(Root)
    private_builder.override_provider("private", module=Root).use_value("no")
    with pytest.raises(BootstrapError, match="private"):
        await private_builder.compile()


@pytest.mark.asyncio
async def test_module_override_happens_before_deferred_materialization() -> None:
    materialized: list[str] = []

    @module(providers=[ValueProvider("value", "replacement")], exports=["value"])
    class Replacement:
        pass

    class Dynamic:
        pass

    def materialize():
        materialized.append("original")
        return ValueModuleSpec

    ValueModuleSpec = ModuleSpec(
        providers=[ValueProvider("value", "original")], exports=["value"]
    )
    descriptor = DeferredModule(Dynamic, "default", materialize)

    @module(imports=[descriptor])
    class Root:
        pass

    builder = TestingModule.create(Root)
    builder.replace_module(descriptor, Replacement)
    application = await builder.compile()
    assert materialized == []
    assert await application.resolve("value") == "replacement"
    await application.close()


@pytest.mark.asyncio
async def test_testing_application_resolves_dynamic_module_identity() -> None:
    class Dynamic:
        pass

    descriptor = DeferredModule(
        Dynamic,
        "configured",
        lambda: ModuleSpec(
            providers=[ValueProvider("value", "configured")],
            exports=["value"],
        ),
    )

    @module(imports=[descriptor])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    value = await application.resolve("value", module=(Dynamic, "configured"))
    assert value == "configured"
    await application.close()


@pytest.mark.asyncio
async def test_http_client_requires_a_starlette_adapter() -> None:
    @module()
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        with pytest.raises(ApplicationStateError, match="does not use"):
            async with application.http_client():
                raise AssertionError("unreachable")
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_http_client_reports_missing_optional_dependency(monkeypatch) -> None:
    @module()
    class Root:
        pass

    application = await TestingModule.create(Root).compile(adapter=StarletteAdapter())
    monkeypatch.setitem(sys.modules, "httpx", None)
    try:
        with pytest.raises(BootstrapError, match=r"tori-py-framework\[testing\]"):
            async with application.http_client():
                raise AssertionError("unreachable")
    finally:
        await application.close()


@pytest.mark.asyncio
async def test_http_client_rejects_unstarted_and_stopped_applications() -> None:
    @module()
    class Root:
        pass

    application = await NestApplication.create(Root, adapter=StarletteAdapter())
    with pytest.raises(ApplicationStateError, match="started application"):
        async with http_client(application):
            raise AssertionError("unreachable")

    await application.start()
    await application.shutdown()
    with pytest.raises(ApplicationStateError, match="started application"):
        async with http_client(application):
            raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_exported_injectable_shorthand_can_be_overridden() -> None:
    @injectable()
    class Service:
        pass

    replacement = object()

    @module(providers=[Service], exports=[Service])
    class Root:
        pass

    builder = TestingModule.create(Root)
    builder.override_provider(Service, module=Root).use_value(replacement)
    application = await builder.compile()

    assert await application.resolve(Service, module=Root) is replacement
    await application.close()


@pytest.mark.asyncio
async def test_unknown_override_target_is_rejected() -> None:
    @module(providers=[ValueProvider("value", "original")], exports=["value"])
    class Root:
        pass

    @module()
    class Missing:
        pass

    builder = TestingModule.create(Root)
    builder.override_provider("value", module=Missing).use_value("replacement")
    adapter = StarletteAdapter()
    with pytest.raises(BootstrapError, match="not present"):
        await builder.compile(adapter=adapter)
    application = await TestingModule.create(Root).compile(adapter=adapter)
    await application.close()


@pytest.mark.asyncio
async def test_testing_application_uses_production_resource_shutdown() -> None:
    events: list[str] = []

    @asynccontextmanager
    async def resource() -> AsyncIterator[str]:
        events.append("enter")
        yield "value"
        events.append("exit")

    from tori_py import FactoryProvider

    @module(providers=[FactoryProvider("resource", resource)])
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    assert await application.resolve("resource") == "value"
    await application.close()
    assert events == ["enter", "exit"]
