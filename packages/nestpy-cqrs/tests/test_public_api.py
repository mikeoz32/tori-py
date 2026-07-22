import subprocess
import sys
from pathlib import Path
from typing import Any, cast

import pytest
from cqrs_core import Command, Event, HandlerKind, Query
from nestpy_cqrs import (
    CqrsConfigurationError,
    CqrsHandlerBinding,
    CqrsModule,
    CqrsModuleOptions,
    command_handler,
    event_handler,
    query_handler,
)


class Create(Command[int]):
    pass


class Read(Query[int]):
    pass


class Created(Event):
    pass


def test_public_facade_and_binding_helpers() -> None:
    assert command_handler(Create, "create") == CqrsHandlerBinding(
        kind=HandlerKind.COMMAND,
        message_type=Create,
        token="create",
    )
    assert query_handler(Read, "read").token == "read"
    assert event_handler(Created, "created").token == "created"
    assert CqrsModuleOptions()
    assert CqrsModule
    assert CqrsModule.for_root()


def test_invalid_binding_category_and_token_are_rejected() -> None:
    with pytest.raises(CqrsConfigurationError, match="concrete Command"):
        command_handler(cast(Any, Created), "handler")
    with pytest.raises(CqrsConfigurationError, match="token"):
        event_handler(Created, cast(Any, object()))
    with pytest.raises(CqrsConfigurationError, match="event_error_handler"):
        CqrsModuleOptions(event_error_handler=cast(Any, object()))


def test_duplicate_event_provider_binding_is_rejected() -> None:
    duplicate = event_handler(Created, "created")
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
import nestpy_cqrs
assert 'starlette' not in sys.modules
assert 'fastapi' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'NestpyHandlerProvider' not in nestpy_cqrs.__all__
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    package_root = Path(__file__).parents[1]
    assert (package_root / "src" / "nestpy_cqrs" / "py.typed").is_file()
