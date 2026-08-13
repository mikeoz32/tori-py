"""Root module for the project structure example."""

from tori_py import ClassProvider, module

from examples.tori_py.getting_started.project_structure.controllers import (
    ProjectController,
)
from examples.tori_py.getting_started.project_structure.services import ClockService


@module(
    providers=[ClassProvider(ClockService)],
    controllers=[ProjectController],
)
class AppModule:
    pass
