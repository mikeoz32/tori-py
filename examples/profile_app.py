"""Minimal FastAPI profile acceptance application."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fastapi import Depends, FastAPI, Request
from tori_py_cqrs_core import (
    Command,
    CommandBus,
    CqrsBuses,
    Event,
    EventBus,
    Query,
    QueryBus,
)
from tori_py_cqrs_fastapi import (
    FastAPIAdapter,
    FastAPIHandlerProvider,
    get_command_bus,
    get_query_bus,
)


@dataclass(frozen=True, slots=True)
class CreateProfile(Command[int]):
    username: str


@dataclass(frozen=True, slots=True)
class GetProfile(Query[dict[str, Any] | None]):
    profile_id: int


@dataclass(frozen=True, slots=True)
class ProfileCreated(Event):
    profile_id: int


class InMemoryProfileRepository:
    def __init__(self) -> None:
        self._profiles: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    def create(self, username: str) -> int:
        profile_id = self._next_id
        self._next_id += 1
        self._profiles[profile_id] = {"id": profile_id, "username": username}
        return profile_id

    def get(self, profile_id: int) -> dict[str, Any] | None:
        return self._profiles.get(profile_id)


@dataclass(slots=True)
class ProfileServices:
    repository: InMemoryProfileRepository
    event_bus: EventBus | None = None
    event_log: list[int] = field(default_factory=list)


def create_profile_app() -> FastAPI:
    """Create the profile app using adapter-owned handler registration."""

    repository = InMemoryProfileRepository()
    services = ProfileServices(repository=repository)
    provider = FastAPIHandlerProvider({ProfileServices: services})

    def on_buses_built(buses: CqrsBuses) -> None:
        services.event_bus = buses.event_bus

    adapter = FastAPIAdapter(
        provider=provider,
        on_buses_built=on_buses_built,
    )

    @adapter.command_handler(CreateProfile)
    class CreateProfileHandler:
        def __init__(self, services: ProfileServices) -> None:
            self._services = services

        async def handle(self, message: CreateProfile) -> int:
            profile_id = self._services.repository.create(message.username)
            if self._services.event_bus is None:
                raise RuntimeError("profile event bus is not initialized")
            await self._services.event_bus.publish(ProfileCreated(profile_id))
            return profile_id

    @adapter.query_handler(GetProfile)
    class GetProfileHandler:
        def __init__(self, services: ProfileServices) -> None:
            self._services = services

        async def handle(self, message: GetProfile) -> dict[str, Any] | None:
            return self._services.repository.get(message.profile_id)

    @adapter.event_handler(ProfileCreated)
    class ProfileCreatedHandler:
        def __init__(self, services: ProfileServices) -> None:
            self._services = services

        async def handle(self, message: ProfileCreated) -> None:
            self._services.event_log.append(message.profile_id)

    app = FastAPI(lifespan=adapter.lifespan)
    app.state.cqrs_adapter = adapter
    app.state.profile_repository = repository
    app.state.profile_event_log = services.event_log

    _command_dependency = Depends(get_command_bus)
    _query_dependency = Depends(get_query_bus)

    @app.post("/profiles")
    async def create_profile(
        request: Request,
        command_bus: CommandBus = _command_dependency,
    ) -> dict[str, int]:
        payload = await request.json()
        return {
            "profile_id": await command_bus.execute(CreateProfile(payload["username"]))
        }

    @app.get("/profiles/{profile_id}")
    async def get_profile(
        profile_id: int,
        query_bus: QueryBus = _query_dependency,
    ) -> dict[str, Any] | None:
        return await query_bus.execute(GetProfile(profile_id))

    return app
