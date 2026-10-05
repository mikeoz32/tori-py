from typing import cast

import pytest
from tori_py.testing import TestingModule, http_client

from examples.tori_py.method_interception.app import (
    AuthorizationExampleModule,
    CallerContext,
    InProcessDocumentActions,
    PermissionDenied,
    create_application,
)


@pytest.mark.asyncio
async def test_method_policy_is_shared_by_http_and_in_process_work_scope() -> None:
    application = await create_application()
    await application.start()
    try:
        async with http_client(application) as client:
            reader = {"authorization": "Bearer reader-token"}
            publisher = {"authorization": "Bearer publisher-token"}

            readable = await client.get("/documents/42", headers=reader)
            assert readable.status_code == 200
            assert readable.json() == {
                "id": "42",
                "body": "example document",
            }

            forbidden = await client.post(
                "/documents/42/publish",
                headers=reader,
            )
            assert forbidden.status_code == 403
            assert forbidden.json() == {"detail": "Permission denied."}

            published = await client.post(
                "/documents/42/publish",
                headers=publisher,
            )
            assert published.status_code == 200
            assert published.json() == {"id": "42", "status": "published"}

            unauthenticated = await client.get("/documents/42")
            assert unauthenticated.status_code == 403
    finally:
        await application.shutdown()

    testing_application = await TestingModule.create(
        AuthorizationExampleModule
    ).compile()
    try:
        actions = cast(
            InProcessDocumentActions,
            await testing_application.resolve(InProcessDocumentActions),
        )
        assert await actions.publish(
            CallerContext("publisher", frozenset({"documents:publish"})),
            "43",
        ) == {"id": "43", "status": "published"}

        with pytest.raises(PermissionDenied, match="documents:publish"):
            await actions.publish(
                CallerContext("reader", frozenset({"documents:read"})),
                "43",
            )
    finally:
        await testing_application.close()
