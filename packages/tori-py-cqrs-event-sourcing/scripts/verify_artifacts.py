"""Smoke-test tori-py-cqrs-event-sourcing wheel and source distributions."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

SMOKE = r"""
import asyncio
from dataclasses import dataclass
from importlib.metadata import requires
from pathlib import Path
import re
from typing import Annotated

import tori_py_cqrs_event_sourcing
from tori_py_cqrs_core import Command, CommandBus, Event
from tori_py_cqrs_event_sourcing_core import (
    AggregateRoot,
    EventSchema,
    EventSchemaRegistry,
    EventSourcedRepository,
    InMemoryEventStore,
)
from tori_py import ClassProvider, Scope, module
from tori_py.testing import TestingModule
from tori_py_cqrs import CqrsModule, command_handler
from tori_py_cqrs_event_sourcing import (
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
    aggregate_repository,
    use_event_sourcing,
)

assert CqrsEventSourcingModule
assert Path(tori_py_cqrs_event_sourcing.__file__).with_name("py.typed").is_file()
names = {
    re.sub(r"[-_.]+", "-", re.match(r"[A-Za-z0-9_.-]+", item).group().lower())
    for item in (requires("tori-py-cqrs-event-sourcing") or [])
}
assert names == {
    "tori-py",
    "tori-py-cqrs",
    "tori-py-cqrs-core",
    "tori-py-cqrs-event-sourcing-core",
}

@dataclass(frozen=True, slots=True)
class Opened(Event):
    name: str

class Member(AggregateRoot[int]):
    def __init__(self, member_id: int) -> None:
        super().__init__(member_id)
        self.name = ""
    def open(self, name: str) -> None:
        self.raise_event(Opened(name))
    def _apply(self, event: Event) -> None:
        self.name = event.name

@aggregate_repository(Member, category="member")
class Members(EventSourcedRepository[int, Member]):
    pass

schemas = EventSchemaRegistry().register(
    EventSchema(
        "member.opened",
        1,
        Opened,
        lambda event: event.name.encode(),
        lambda payload: Opened(payload.decode()),
    )
).freeze()

@dataclass(frozen=True, slots=True)
class Open(Command[Member]):
    member_id: int

@use_event_sourcing(key="smoke")
@command_handler(Open, scope=Scope.REQUEST)
class Handler:
    def __init__(
        self,
        members: Annotated[Members, aggregate_repository(Members)],
    ) -> None:
        self.members = members
    async def handle(self, command: Open) -> Member:
        member = Member(command.member_id)
        member.open("smoke")
        self.members.save(member)
        return member

@module(providers=[ClassProvider(InMemoryEventStore)], exports=[InMemoryEventStore])
class Persistence:
    pass

event_sourcing = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(store=InMemoryEventStore, schemas=schemas),
    imports=[Persistence],
    key="smoke",
)
repositories = CqrsEventSourcingModule.for_feature(
    [Members],
    root_key="smoke",
)

@module(
    imports=[repositories],
    providers=[Handler],
)
class Feature:
    pass

cqrs = CqrsModule.for_root(key="smoke")

@module(imports=[event_sourcing, Feature, cqrs])
class App:
    pass

async def verify() -> None:
    application = await TestingModule.create(App).compile()
    commands = await application.resolve(CommandBus, module=(CqrsModule, "smoke"))
    store = await application.resolve(InMemoryEventStore, module=Persistence)
    member = await commands.execute(Open(1))
    assert member.name == "smoke" and member.version == 1
    assert len(await store.read_all(limit=10)) == 1
    await application.close()

asyncio.run(verify())
"""


def _one(dist: Path, pattern: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(f"expected one {pattern} artifact, found {len(matches)}")
    return matches[0]


def _verify_contents(artifact: Path) -> None:
    if artifact.suffix == ".whl":
        with zipfile.ZipFile(artifact) as archive:
            names = set(archive.namelist())
        assert "tori_py_cqrs_event_sourcing/py.typed" in names
        assert not any("/tests/" in name for name in names)
        return
    with tarfile.open(artifact, "r:gz") as archive:
        names = set(archive.getnames())
    assert any(
        name.endswith("/src/tori_py_cqrs_event_sourcing/py.typed") for name in names
    )
    assert any(name.endswith("/pyproject.toml") for name in names)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    dist = Path(sys.argv[1]).resolve()
    dependency_names = (
        "tori_py_cqrs_core",
        "tori_py_cqrs_event_sourcing_core",
        "tori_py",
        "tori_py_cqrs",
    )
    for suffix in ("*.whl", "*.tar.gz"):
        artifacts = [_one(dist, f"{name}-{suffix}") for name in dependency_names]
        package_artifact = _one(dist, f"tori_py_cqrs_event_sourcing-{suffix}")
        _verify_contents(package_artifact)
        artifacts.append(package_artifact)
        command = ["uv", "run", "--isolated", "--no-project"]
        for artifact in artifacts:
            command.extend(("--with", str(artifact)))
        command.extend(("python", "-c", SMOKE))
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifacts[-1].name}")


if __name__ == "__main__":
    main()
