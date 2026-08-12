from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

SMOKE = """
import asyncio
from uuid import uuid4
from persistent_streams import (
    AppendRequest, Beginning, CheckpointStrategy, ConsumerRunner,
    InMemoryPersistentLog, StreamDefinition, Subscription,
)

async def main():
    log = InMemoryPersistentLog()
    await log.declare_stream(StreamDefinition("artifact", 1))
    await log.append("artifact", AppendRequest(uuid4(), b"key", b"payload"))
    lease = await log.acquire(
        Subscription("artifact", "smoke", "owner", Beginning()),
        0,
        strategy=CheckpointStrategy.BROKER_MANAGED,
    )
    seen = []
    async def handle(record):
        seen.append(record.payload)
    assert await ConsumerRunner().run_once(lease, handle) == 1
    assert seen == [b"payload"]
    await log.close()

asyncio.run(main())
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args()
    for artifact in args.artifacts:
        subprocess.run(
            [
                "uv",
                "run",
                "--isolated",
                "--no-project",
                "--with",
                str(artifact.resolve()),
                "python",
                "-c",
                SMOKE,
            ],
            check=True,
        )


if __name__ == "__main__":
    main()
