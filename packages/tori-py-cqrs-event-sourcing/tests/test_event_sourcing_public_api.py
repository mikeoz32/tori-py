import ast
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import tori_py_cqrs_event_sourcing
from tori_py import Inject, ModuleSpec
from tori_py_cqrs_core import Command, CommandHandler, Query, QueryHandler
from tori_py_cqrs_event_sourcing import (
    CqrsEventSourcingConfigurationError,
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
    aggregate_repository,
    event_sourcing_transaction,
    get_command_synchronization_token,
    get_event_store_token,
    get_schema_registry_token,
    get_transaction_interceptor_token,
    use_event_sourcing,
)
from tori_py_cqrs_event_sourcing_core import (
    AggregateRoot,
    EventSchemaRegistry,
    EventSourcedRepository,
    EventStore,
)


class Member(AggregateRoot[int]):
    def _apply(self, event) -> None:
        del event


@aggregate_repository(Member, category="member")
class MemberRepo(EventSourcedRepository[int, Member]):
    pass


def test_public_api_allowlist_and_type_marker() -> None:
    assert set(tori_py_cqrs_event_sourcing.__all__) == {
        "CommandCancellationError",
        "CommandFinalizationPhase",
        "CommandSynchronization",
        "CommandSynchronizationStateError",
        "CommandTransactionUnavailableError",
        "ConfirmedCommandFinalizationError",
        "ConfirmedNonCommitFinalizationError",
        "CqrsEventSourcingConfigurationError",
        "CqrsEventSourcingError",
        "CqrsEventSourcingModule",
        "CqrsEventSourcingOptions",
        "IndeterminateCommandFinalizationError",
        "UnitOfWorkFactory",
        "aggregate_repository",
        "default_unit_of_work_factory",
        "event_sourcing_transaction",
        "get_command_synchronization_token",
        "get_event_store_token",
        "get_schema_registry_token",
        "get_transaction_interceptor_token",
        "use_event_sourcing",
    }
    package_root = Path(__file__).parents[1]
    assert (package_root / "src/tori_py_cqrs_event_sourcing/py.typed").is_file()
    assert (package_root / "README.md").is_file()


def test_repository_declaration_and_injection_forms_are_exact() -> None:
    marker = aggregate_repository(MemberRepo)
    assert marker == Inject(MemberRepo)

    class Undecorated(EventSourcedRepository[int, Member]):
        pass

    with pytest.raises(CqrsEventSourcingConfigurationError, match="decorated"):
        aggregate_repository(Undecorated)
    with pytest.raises(CqrsEventSourcingConfigurationError, match="does not accept"):
        aggregate_repository(cast(Any, MemberRepo), category="other")
    with pytest.raises(CqrsEventSourcingConfigurationError, match="does not accept"):
        cast(Callable[..., object], aggregate_repository)(
            MemberRepo,
            page_size=None,
        )
    with pytest.raises(CqrsEventSourcingConfigurationError, match="only once"):
        aggregate_repository(Member, category="member")(MemberRepo)

    class Inherited(MemberRepo):
        pass

    with pytest.raises(CqrsEventSourcingConfigurationError, match="directly decorated"):
        aggregate_repository(Inherited)


def test_transaction_decorator_requires_command_metadata_and_uses_key() -> None:
    class Create(Command[None]):
        pass

    class Read(Query[None]):
        pass

    @use_event_sourcing(key="community")
    @CommandHandler(Create)
    class Handler:
        async def handle(self, command: Create) -> None:
            del command

    assert Handler
    assert event_sourcing_transaction(key="community").handler_kinds is not None

    with pytest.raises(CqrsEventSourcingConfigurationError, match="command"):

        @use_event_sourcing()
        @QueryHandler(Read)
        class QueryHandlerClass:
            pass

    with pytest.raises(CqrsEventSourcingConfigurationError, match="command"):
        use_event_sourcing()(cast(Any, object()))


def test_keyed_tokens_are_stable_and_distinct() -> None:
    tokens = {
        get_event_store_token(key="community"),
        get_schema_registry_token(key="community"),
        get_command_synchronization_token(key="community"),
        get_transaction_interceptor_token(key="community"),
    }
    assert len(tokens) == 4
    assert get_event_store_token(key="community") == get_event_store_token(
        key="community"
    )


def test_root_feature_identity_and_frozen_schema_validation() -> None:
    schemas = EventSchemaRegistry().freeze()
    root = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(store=EventStore, schemas=schemas),
        key="community",
    )
    feature = CqrsEventSourcingModule.for_feature(
        [MemberRepo],
        root_key="community",
    )
    assert root.module is CqrsEventSourcingModule
    assert feature.module is not root.module
    assert feature.key == "community:default"
    repeated = CqrsEventSourcingModule.for_feature(
        [MemberRepo],
        root_key="community",
    )
    assert repeated.module is not feature.module
    feature_spec = feature.factory()
    root_spec = root.factory()
    assert isinstance(feature_spec, ModuleSpec)
    assert isinstance(root_spec, ModuleSpec)
    assert feature_spec.imports == ()
    assert feature_spec.exports == (MemberRepo,)
    assert root_spec.global_ is True

    unfrozen = CqrsEventSourcingModule.for_root(
        CqrsEventSourcingOptions(
            store=EventStore,
            schemas=EventSchemaRegistry(),
        ),
        key="unfrozen",
    )
    with pytest.raises(CqrsEventSourcingConfigurationError, match="frozen"):
        unfrozen.factory()


def test_runtime_imports_only_declared_architecture_dependencies() -> None:
    script = """
import sys
import tori_py_cqrs_event_sourcing
for name in ('fastapi', 'pydantic', 'sqlalchemy', 'starlette', 'redis'):
    assert name not in sys.modules
assert 'EventSourcingUnitOfWork' not in tori_py_cqrs_event_sourcing.__all__
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr

    source = Path(__file__).parents[1] / "src/tori_py_cqrs_event_sourcing"
    dependency_roots = {
        "tori_py_cqrs_core",
        "tori_py_cqrs_event_sourcing_core",
        "tori_py",
        "tori_py_cqrs",
        "tori_py_cqrs_event_sourcing",
    }
    for path in source.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in dependency_roots - {"tori_py_cqrs_event_sourcing"}:
                    assert not any(alias.name.startswith("_") for alias in node.names)
