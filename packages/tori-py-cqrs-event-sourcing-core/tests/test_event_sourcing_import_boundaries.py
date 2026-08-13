import subprocess
import sys
from pathlib import Path


def test_facade_import_has_no_optional_infrastructure_dependencies() -> None:
    script = """
import sys
import tori_py_cqrs_event_sourcing_core
assert 'fastapi' not in sys.modules
assert 'tori_py' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'msgspec' not in sys.modules
assert 'sqlalchemy' not in sys.modules
assert 'starlette' not in sys.modules
assert 'AggregateRoot' in tori_py_cqrs_event_sourcing_core.__all__
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

    assert (
        package_root / "src" / "tori_py_cqrs_event_sourcing_core" / "py.typed"
    ).is_file()
    assert 'name = "tori-py-cqrs-event-sourcing-core"' in package_metadata
    assert '"tori-py-cqrs-core"' in package_metadata
    assert "packages/tori-py-cqrs-event-sourcing-core" in workspace_metadata
    assert (
        'name = "tori-py-cqrs-event-sourcing-core"'
        in (workspace_root / "uv.lock").read_text()
    )
