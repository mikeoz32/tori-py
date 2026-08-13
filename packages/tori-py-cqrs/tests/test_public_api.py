import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from tori_py import (
    BootstrapError,
    ClassProvider,
    Scope,
    compile_graph,
    get_injectable_metadata,
    injectable,
    module,
)
from tori_py_cqrs import (
    CqrsConfigurationError,
    CqrsHandlerBinding,
    CqrsModule,
    CqrsModuleOptions,
    bind_command_handler,
    bind_event_handler,
    bind_query_handler,
    command_handler,
    event_handler,
    query_handler,
)
from tori_py_cqrs_core import (
    Command,
    Event,
    HandlerKind,
    InvalidHandlerRegistrationError,
    Query,
    get_handler_metadata,
)
from tori_py_cqrs_core import (
    CommandHandler as CoreCommandHandler,
)


class Create(Command[int]):
    pass


class Read(Query[int]):
    pass


class Created(Event):
    pass


def test_public_facade_and_binding_helpers() -> None:
    assert bind_command_handler(Create, "create") == CqrsHandlerBinding(
        kind=HandlerKind.COMMAND,
        message_type=Create,
        token="create",
    )
    assert bind_query_handler(Read, "read").token == "read"
    assert bind_event_handler(Created, "created").token == "created"
    assert CqrsModuleOptions()
    assert CqrsModule
    assert CqrsModule.for_root()


@pytest.mark.asyncio
async def test_handler_decorators_add_cqrs_and_injectable_metadata() -> None:
    @command_handler(Create, scope=Scope.REQUEST, manage=False)
    class CreateHandler:
        async def handle(self, command: Create) -> int:
            return 1

    @query_handler(Read, scope=Scope.TRANSIENT)
    class ReadHandler:
        async def handle(self, query: Read) -> int:
            return 1

    @event_handler(Created)
    class CreatedHandler:
        async def handle(self, event: Created) -> None:
            return None

    @module(providers=[CreateHandler, ReadHandler, CreatedHandler])
    class Feature:
        pass

    graph = await compile_graph(Feature)
    create_plan = graph.providers[graph.visibility[(graph.root, CreateHandler)]]
    read_plan = graph.providers[graph.visibility[(graph.root, ReadHandler)]]
    event_plan = graph.providers[graph.visibility[(graph.root, CreatedHandler)]]

    create_metadata = get_handler_metadata(CreateHandler)
    read_metadata = get_handler_metadata(ReadHandler)
    event_metadata = get_handler_metadata(CreatedHandler)
    assert create_metadata is not None
    assert read_metadata is not None
    assert event_metadata is not None
    assert create_metadata.kind is HandlerKind.COMMAND
    assert read_metadata.kind is HandlerKind.QUERY
    assert event_metadata.kind is HandlerKind.EVENT
    assert isinstance(create_plan.declaration, ClassProvider)
    assert create_plan.declaration.manage is False
    assert create_plan.scope is Scope.REQUEST
    assert read_plan.scope is Scope.TRANSIENT
    assert event_plan.scope is Scope.SINGLETON


def test_handler_decorator_conflicts_do_not_leave_partial_metadata() -> None:
    @injectable()
    class ExistingProvider:
        pass

    with pytest.raises(BootstrapError, match="already declared"):
        command_handler(Create)(ExistingProvider)
    assert get_handler_metadata(ExistingProvider) is None

    @CoreCommandHandler(Create)
    class ExistingHandler:
        pass

    with pytest.raises(InvalidHandlerRegistrationError, match="already has"):
        command_handler(Create)(ExistingHandler)
    assert get_injectable_metadata(ExistingHandler) is None


def test_invalid_binding_category_and_token_are_rejected() -> None:
    with pytest.raises(CqrsConfigurationError, match="concrete Command"):
        bind_command_handler(cast(Any, Created), "handler")
    with pytest.raises(CqrsConfigurationError, match="token"):
        bind_event_handler(Created, cast(Any, object()))
    with pytest.raises(CqrsConfigurationError, match="event_error_handler"):
        CqrsModuleOptions(event_error_handler=cast(Any, object()))


def test_duplicate_event_provider_binding_is_rejected() -> None:
    duplicate = bind_event_handler(Created, "created")
    with pytest.raises(CqrsConfigurationError, match="duplicate event"):
        CqrsModule.for_root(
            handlers=[duplicate, duplicate],
            key="duplicate",
        )


def test_invalid_module_options_and_handler_values_are_rejected() -> None:
    with pytest.raises(CqrsConfigurationError, match="handlers must be iterable"):
        CqrsModule.for_root(handlers=cast(Any, None))
    with pytest.raises(CqrsConfigurationError, match="CqrsHandlerBinding"):
        CqrsModule.for_root(handlers=cast(Any, [object()]))
    with pytest.raises(CqrsConfigurationError, match="CqrsModuleOptions"):
        CqrsModule.for_root(handlers=[], options=cast(Any, object()))


def test_import_boundaries_and_type_marker() -> None:
    script = """
import sys
import tori_py_cqrs
assert 'starlette' not in sys.modules
assert 'fastapi' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'ToriPyHandlerProvider' not in tori_py_cqrs.__all__
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    package_root = Path(__file__).parents[1]
    assert (package_root / "src" / "tori_py_cqrs" / "py.typed").is_file()
