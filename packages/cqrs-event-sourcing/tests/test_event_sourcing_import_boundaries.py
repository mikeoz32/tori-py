import subprocess
import sys
from pathlib import Path


def test_facade_import_has_no_optional_infrastructure_dependencies() -> None:
    script = """
import sys
import cqrs_event_sourcing
assert 'fastapi' not in sys.modules
assert 'nestpy' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'msgspec' not in sys.modules
assert 'sqlalchemy' not in sys.modules
assert 'starlette' not in sys.modules
assert 'AggregateRoot' in cqrs_event_sourcing.__all__
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_workspace_metadata_and_type_marker_exist() -> None:
    package_root = Path(__file__).parents[1]
    workspace_root = package_root.parents[1]
    package_metadata = (package_root / "pyproject.toml").read_text()
    workspace_metadata = (workspace_root / "pyproject.toml").read_text()

    assert (package_root / "src" / "cqrs_event_sourcing" / "py.typed").is_file()
    assert 'name = "cqrs-event-sourcing"' in package_metadata
    assert '"cqrs-core"' in package_metadata
    assert "packages/cqrs-event-sourcing" in workspace_metadata
    assert 'name = "cqrs-event-sourcing"' in (workspace_root / "uv.lock").read_text()
