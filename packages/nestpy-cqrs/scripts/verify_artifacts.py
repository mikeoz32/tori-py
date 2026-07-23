"""Smoke-test nestpy-cqrs artifacts with local dependency artifacts."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMOKE = r"""
import asyncio
from dataclasses import dataclass
from pathlib import Path

import nestpy_cqrs
from cqrs_core import Command, CommandBus
from nestpy import module
from nestpy.testing import TestingModule
from nestpy_cqrs import CqrsModule, command_handler

@dataclass(frozen=True, slots=True)
class Echo(Command[str]):
    value: str

@command_handler(Echo)
class EchoHandler:
    async def handle(self, command: Echo) -> str:
        return command.value

@module(providers=[EchoHandler], exports=[EchoHandler])
class Handlers:
    pass

cqrs = CqrsModule.for_root()

@module(imports=[Handlers, cqrs])
class Root:
    pass

async def smoke() -> None:
    application = await TestingModule.create(Root).compile()
    try:
        commands = await application.resolve(CommandBus, module=(CqrsModule, "default"))
        assert isinstance(commands, CommandBus)
        assert await commands.execute(Echo("artifact")) == "artifact"
    finally:
        await application.close()

assert Path(nestpy_cqrs.__file__).with_name("py.typed").is_file()
asyncio.run(smoke())
"""


def _one(dist: Path, pattern: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(
            f"expected one {pattern} artifact in {dist}, found {len(matches)}"
        )
    return matches[0]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    dist = Path(sys.argv[1]).resolve()
    artifact_sets = (
        (
            _one(dist, "cqrs_core-*.whl"),
            _one(dist, "nestpy-*.whl"),
            _one(dist, "nestpy_cqrs-*.whl"),
        ),
        (
            _one(dist, "cqrs_core-*.tar.gz"),
            _one(dist, "nestpy-*.tar.gz"),
            _one(dist, "nestpy_cqrs-*.tar.gz"),
        ),
    )
    for artifacts in artifact_sets:
        command = ["uv", "run", "--isolated"]
        for artifact in artifacts:
            command.extend(("--with", str(artifact)))
        command.extend(("python", "-c", SMOKE))
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifacts[-1].name}")


if __name__ == "__main__":
    main()
