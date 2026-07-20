import subprocess
import sys
from pathlib import Path


def test_core_import_does_not_load_driver_or_server_modules() -> None:
    script = """
import sys
import nestpy.core
import nestpy.application
import nestpy.http
from nestpy import NestApplication
assert 'starlette' not in sys.modules
assert 'uvicorn' not in sys.modules
assert 'fastapi' not in sys.modules
assert 'cqrs_core' not in sys.modules
assert 'opentelemetry' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'dependency_injector' not in sys.modules
assert 'sqlalchemy' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_optional_namespaces_and_type_marker_import_without_server() -> None:
    script = """
import nestpy
import nestpy.application
import nestpy.http
import nestpy.cli
import nestpy.settings
import nestpy.starlette
import nestpy.testing
import sys
assert 'msgspec' in sys.modules
assert 'starlette' not in sys.modules
assert 'uvicorn' not in sys.modules
assert 'yaml' not in sys.modules
assert 'NestApplication' in nestpy.__all__
assert 'StarletteOptions' not in nestpy.__all__
assert 'NestApplication' not in nestpy.starlette.__all__
assert 'HttpException' not in nestpy.starlette.__all__
assert 'MsgspecValidationPipe' not in nestpy.starlette.__all__
assert 'PipelineExecutor' not in nestpy.starlette.__all__
assert {
    'HttpPipelineAdapter',
    'PipelineExecutor',
    'ParameterPlan',
    'RoutePlan',
    'bind_routes',
    'compile_routes',
}.issubset(nestpy.http.__all__)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_package_type_marker_and_workspace_metadata_exist() -> None:
    package_root = Path(__file__).parents[1]
    workspace_root = package_root.parents[1]
    assert (package_root / "src" / "nestpy" / "py.typed").is_file()
    pyproject = (package_root / "pyproject.toml").read_text()
    assert 'name = "nestpy"' in pyproject
    assert "starlette" in pyproject
    assert "msgspec" in pyproject
    assert "packages/nestpy" in (workspace_root / "pyproject.toml").read_text()
    assert 'name = "nestpy"' in (workspace_root / "uv.lock").read_text()


def test_old_starlette_application_import_is_removed() -> None:
    script = """
try:
    from nestpy.starlette.application import NestApplication
except ImportError:
    pass
else:
    raise AssertionError('old NestApplication import remains available')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_framework_http_symbols_are_removed_from_starlette_modules() -> None:
    script = """
imports = (
    'from nestpy.starlette.errors import HttpException',
    'from nestpy.starlette.pipeline import MsgspecValidationPipe',
    'from nestpy.starlette.pipeline import PipelineExecutor',
)
for statement in imports:
    try:
        exec(statement)
    except ImportError:
        pass
    else:
        raise AssertionError(f'old transport-owned import remains: {statement}')
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_framework_http_execution_modules_do_not_load_starlette() -> None:
    script = """
import sys
import nestpy.core.pipeline
import nestpy.http.pipeline
import nestpy.http.routes
assert 'starlette' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
