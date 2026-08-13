"""Controller declarations for the project structure example."""

from tori_py import controller, get

from examples.tori_py.getting_started.project_structure.services import ClockService


@controller("/project")
class ProjectController:
    def __init__(self, clock: ClockService) -> None:
        self._clock = clock

    @get("/message")
    async def message(self) -> dict[str, str]:
        return {"message": self._clock.greeting()}
