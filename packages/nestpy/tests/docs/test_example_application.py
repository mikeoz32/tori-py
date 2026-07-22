import pytest
from nestpy.testing import http_client

from examples.nestpy.app import create_application


@pytest.mark.asyncio
async def test_documented_example_serves_one_request() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            response = await client.get("/example/health", params={"count": 2})
    finally:
        await application.shutdown()
    assert response.status_code == 200
    assert response.json() == {
        "status": "hello",
        "count": 2,
        "request_value": "request",
    }
