import subprocess
import sys
from pathlib import Path


def test_core_import_does_not_load_driver_or_server_modules() -> None:
    script = """
import sys
import tori_py.core
import tori_py.application
import tori_py.http
from tori_py import NestApplication
assert 'starlette' not in sys.modules
assert 'uvicorn' not in sys.modules
assert 'fastapi' not in sys.modules
assert 'tori_py_cqrs_core' not in sys.modules
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
import tori_py
import tori_py.application
import tori_py.http
import tori_py.cli
import tori_py.settings
import tori_py.starlette
import tori_py.testing
import sys
assert 'msgspec' in sys.modules
assert 'starlette' not in sys.modules
assert 'uvicorn' not in sys.modules
assert 'yaml' not in sys.modules
assert 'httpx' not in sys.modules
assert 'NestApplication' in tori_py.__all__
assert {'HttpResponse', 'ResponseHeaderMetadata', 'header'}.issubset(tori_py.__all__)
assert 'StarletteOptions' not in tori_py.__all__
assert 'NestApplication' not in tori_py.starlette.__all__
assert 'HttpException' not in tori_py.starlette.__all__
assert 'MsgspecValidationPipe' not in tori_py.starlette.__all__
assert 'PipelineExecutor' not in tori_py.starlette.__all__
assert {
    'HttpPipelineAdapter',
    'PipelineExecutor',
    'ParameterPlan',
    'RoutePlan',
    'bind_routes',
    'compile_routes',
    'get_response_header_metadata',
    'header',
}.issubset(tori_py.http.__all__)
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
    assert (package_root / "src" / "tori_py" / "py.typed").is_file()
    pyproject = (package_root / "pyproject.toml").read_text()
    assert 'name = "tori-py"' in pyproject
    assert "starlette" in pyproject
    assert "msgspec" in pyproject
    assert "packages/tori-py" in (workspace_root / "pyproject.toml").read_text()
    assert 'name = "tori-py"' in (workspace_root / "uv.lock").read_text()


def test_old_starlette_application_import_is_removed() -> None:
    script = """
try:
    from tori_py.starlette.application import NestApplication
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
    'from tori_py.starlette.errors import HttpException',
    'from tori_py.starlette.pipeline import MsgspecValidationPipe',
    'from tori_py.starlette.pipeline import PipelineExecutor',
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
import tori_py.core.pipeline
import tori_py.http.pipeline
import tori_py.http.routes
assert 'starlette' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
