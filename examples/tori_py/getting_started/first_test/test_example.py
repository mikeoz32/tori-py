"""The same public TestingModule workflow shown in the guide."""

import pytest
from tori_py.starlette import StarletteAdapter
from tori_py.testing import TestingModule

from examples.tori_py.getting_started.first_test.app import GREETING, AppModule


@pytest.mark.asyncio
async def test_exported_provider_can_be_overridden() -> None:
    builder = TestingModule.create(AppModule)
    builder.override_provider(GREETING, module=AppModule).use_value("Hello from test")
    application = await builder.compile(adapter=StarletteAdapter())
    try:
        async with application.http_client() as client:
            response = await client.get("/greeting")
    finally:
        await application.close()
    assert response.status_code == 200
    assert response.json() == {"message": "Hello from test"}
