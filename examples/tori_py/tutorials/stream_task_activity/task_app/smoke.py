"""Check task activity against the RabbitMQ broker started by compose.yaml."""

import asyncio
import os
from uuid import uuid4

import httpx
from tori_py.testing import http_client

from .app import create_application


async def activity_titles(client: httpx.AsyncClient, marker: str) -> list[str]:
    response = await client.get("/activity")
    response.raise_for_status()
    return sorted(
        entry["title"] for entry in response.json() if marker in entry["title"]
    )


async def main() -> None:
    # The second phase needs a stream that outlives the first process.
    os.environ["TASK_API_STREAMS"] = "rabbitmq"
    marker = uuid4().hex[:8]
    titles = sorted(f"{name} {marker}" for name in ("Plan", "Ship"))

    first = await create_application()
    await first.start()
    try:
        async with http_client(first) as client:
            for title in titles:
                response = await client.post("/tasks", json={"title": title})
                response.raise_for_status()
            async with asyncio.timeout(30):
                while await activity_titles(client, marker) != titles:
                    await asyncio.sleep(0.1)
    finally:
        await first.shutdown()
    print("first process projected", titles)

    # A new process has an empty projection and empty in-memory checkpoints, so
    # it reads the stream from the beginning and rebuilds the same entries.
    second = await create_application()
    await second.start()
    try:
        async with http_client(second) as client:
            async with asyncio.timeout(30):
                while await activity_titles(client, marker) != titles:
                    await asyncio.sleep(0.1)
            tasks = (await client.get("/tasks")).json()
    finally:
        await second.shutdown()
    print("second process rebuilt", titles, "with", len(tasks), "stored tasks")


if __name__ == "__main__":
    asyncio.run(main())
