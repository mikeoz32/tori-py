import httpx
import pytest
from tori_py.starlette import StarletteAdapter

from examples.tori_py.openapi.app import create_application


@pytest.mark.asyncio
async def test_documented_openapi_example() -> None:
    application = await create_application()
    await application.start()
    transport = httpx.ASGITransport(app=application.get_adapter(StarletteAdapter).app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        document_response = await client.get("/openapi.json")
        docs_response = await client.get("/docs")
        denied_response = await client.get("/members/alice?detail=full")
        member_response = await client.get(
            "/members/alice?detail=full",
            headers={"Authorization": "Bearer example-token"},
        )

    assert document_response.status_code == 200
    document = document_response.json()
    read_operation = document["paths"]["/members/{handle}"]["get"]
    assert read_operation["summary"] == "Read a member"
    assert read_operation["description"].startswith(
        "Return the member fields visible to the current caller."
    )
    assert "Internal authorization" not in read_operation["description"]
    assert read_operation["security"] == [{"oidc": []}]
    assert read_operation["responses"]["200"]["headers"] == {
        "Cache-Control": {
            "schema": {"type": "string"},
            "example": "private, no-store",
        }
    }
    assert document["paths"]["/health"]["get"]["security"] == []
    assert docs_response.status_code == 200
    assert "SwaggerUIBundle" in docs_response.text
    assert denied_response.status_code == 403
    assert member_response.json() == {
        "handle": "alice",
        "display_name": "Alice",
        "detail": "full",
    }
    await application.shutdown()
