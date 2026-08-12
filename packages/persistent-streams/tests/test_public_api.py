from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import persistent_streams


def test_public_facade_is_exact() -> None:
    assert set(persistent_streams.__all__) == {
        "AdapterContractError",
        "AppendRequest",
        "AvailableBounds",
        "Beginning",
        "CheckpointError",
        "CheckpointKey",
        "CheckpointPersistenceError",
        "CheckpointStore",
        "CheckpointStrategy",
        "CheckpointStrategyError",
        "ConsumerRunner",
        "CursorKind",
        "DEFAULT_PARTITION_ROUTER",
        "End",
        "ExactOffset",
        "ExternalCheckpointStrategy",
        "InMemoryCheckpointStore",
        "InMemoryPersistentLog",
        "IncompatibleStreamError",
        "InvalidPartitionError",
        "LifecycleError",
        "OwnershipError",
        "OwnershipToken",
        "PartitionLease",
        "PartitionRouter",
        "PersistentLog",
        "PersistentStreamAdapter",
        "PersistentStreamsError",
        "PoisonRecordError",
        "PublishOutcome",
        "PublishReceipt",
        "PublishingConflictError",
        "RecordHandler",
        "RecordPage",
        "RelativeTime",
        "ResourceLimitError",
        "ResumeCursor",
        "RetentionGapError",
        "Sha256PartitionRouter",
        "StalePublishingIdError",
        "StartPosition",
        "StartModeCapabilities",
        "StoredRecord",
        "StreamDefinition",
        "StreamLimits",
        "Subscription",
        "Timestamp",
        "UnknownStreamError",
        "ValidationError",
    }
    assert all(hasattr(persistent_streams, name) for name in persistent_streams.__all__)
    assert "offset" not in persistent_streams.PublishReceipt.__dataclass_fields__


def test_artifacts_and_standard_library_boundary() -> None:
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["name"] == "persistent-streams"
    assert project["project"]["requires-python"] == ">=3.14,<3.15"
    assert project["project"]["dependencies"] == []
    assert (root / "README.md").is_file()
    assert (root / "scripts/verify_artifacts.py").is_file()
    assert (root / "src/persistent_streams/py.typed").is_file()

    forbidden = {
        "aio_pika",
        "cqrs_core",
        "fastapi",
        "msgspec",
        "nestpy",
        "pydantic",
        "sqlalchemy",
        "starlette",
    }
    for source in (root / "src/persistent_streams").glob("*.py"):
        tree = ast.parse(source.read_text())
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
            for alias in node.names
        }
        assert imports.isdisjoint(forbidden), source

    workspace_packages = root.parent
    reverse_imports = []
    for source in workspace_packages.glob("*/src/**/*.py"):
        if root in source.parents:
            continue
        if "persistent_streams" in source.read_text():
            reverse_imports.append(source)
    assert reverse_imports
    assert {
        source.relative_to(workspace_packages).parts[0] for source in reverse_imports
    } == {"nestpy-persistent-streams", "persistent-streams-rabbitmq"}
