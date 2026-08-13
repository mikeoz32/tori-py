"""Smoke-test tori-py-cqrs-event-sourcing-core wheel and source distributions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMOKE = r"""
import asyncio
from dataclasses import dataclass
from importlib.metadata import requires
from pathlib import Path
import re
from uuid import UUID

import tori_py_cqrs_event_sourcing_core
from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import (
    AggregateRoot,
    EventSchema,
    EventSchemaRegistry,
    EventSourcedRepository,
    EventSourcingUnitOfWork,
    InMemoryEventStore,
)

@dataclass(frozen=True, slots=True)
class Opened(Event):
    name: str

class Profile(AggregateRoot[UUID]):
    def __init__(self, profile_id: UUID) -> None:
        super().__init__(profile_id)
        self.name = ""

    def open(self, name: str) -> None:
        self.raise_event(Opened(name))

    def _apply(self, event: Event) -> None:
        if not isinstance(event, Opened):
            raise AssertionError(f"unknown event: {event!r}")
        self.name = event.name

schemas = EventSchemaRegistry().register(
    EventSchema(
        "profile.opened",
        1,
        Opened,
        lambda event: event.name.encode(),
        lambda payload: Opened(payload.decode()),
    )
).freeze()

def repository(unit_of_work):
    return EventSourcedRepository(
        unit_of_work,
        category="profile",
        aggregate_factory=Profile,
        aggregate_type=Profile,
        id_encoder=str,
        schemas=schemas,
    )

async def smoke() -> None:
    store = InMemoryEventStore()
    profile_id = UUID(int=1)
    async with EventSourcingUnitOfWork(store) as unit_of_work:
        profile = Profile(profile_id)
        profile.open("artifact")
        repository(unit_of_work).save(profile)
        result = await unit_of_work.commit()
    assert profile.version == 1
    assert result.events[0].event.encoded.event_type == "profile.opened"

    async with EventSourcingUnitOfWork(store) as unit_of_work:
        loaded = await repository(unit_of_work).get(profile_id)
    assert loaded.name == "artifact"
    assert loaded.version == 1
    assert len(await store.read_all(limit=10)) == 1

assert Path(tori_py_cqrs_event_sourcing_core.__file__).with_name("py.typed").is_file()
runtime_requirements = requires("tori-py-cqrs-event-sourcing-core") or []
assert len(runtime_requirements) == 1
requirement_name = re.match(r"[A-Za-z0-9_.-]+", runtime_requirements[0])
assert requirement_name is not None
normalized_name = re.sub(r"[-_.]+", "-", requirement_name.group().lower())
assert normalized_name == "tori-py-cqrs-core"
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
            _one(dist, "tori_py_cqrs_core-*.whl"),
            _one(dist, "tori_py_cqrs_event_sourcing_core-*.whl"),
        ),
        (
            _one(dist, "tori_py_cqrs_core-*.tar.gz"),
            _one(dist, "tori_py_cqrs_event_sourcing_core-*.tar.gz"),
        ),
    )
    for artifacts in artifact_sets:
        command = ["uv", "run", "--isolated", "--no-project"]
        for artifact in artifacts:
            command.extend(("--with", str(artifact)))
        command.extend(("python", "-c", SMOKE))
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifacts[-1].name}")


if __name__ == "__main__":
    main()
