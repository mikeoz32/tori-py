"""Root module for the project structure example."""

from nestpy import ClassProvider, module

from examples.nestpy.getting_started.project_structure.controllers import (
    ProjectController,
)
from examples.nestpy.getting_started.project_structure.services import ClockService


@module(
    providers=[ClassProvider(ClockService)],
    controllers=[ProjectController],
)
class AppModule:
    pass
