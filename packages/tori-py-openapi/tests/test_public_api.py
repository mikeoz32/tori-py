import subprocess
import sys
import tomllib
from pathlib import Path

import tori_py_openapi
from tori_py import ToriPyError
from tori_py_openapi import (
    OpenApiConfigurationError,
    OpenApiError,
    OpenApiMetadataError,
    OpenApiSchemaError,
)

PUBLIC_API = {
    "BearerSecurityScheme",
    "OpenApiConfigurationError",
    "OpenApiError",
    "OpenApiInfo",
    "OpenApiMetadataError",
    "OpenApiModule",
    "OpenApiOptions",
    "OpenApiSchemaError",
    "OpenApiServer",
    "SwaggerUiOptions",
    "api_exclude",
    "api_operation",
    "api_public",
    "api_response",
    "api_security",
    "api_tags",
}


def test_public_facade_is_the_exact_allowlist() -> None:
    assert set(tori_py_openapi.__all__) == PUBLIC_API
    assert tori_py_openapi.OpenApiModule.__module__ == "tori_py_openapi.module"


def test_error_hierarchy_is_typed_and_has_stable_codes() -> None:
    assert issubclass(OpenApiError, ToriPyError)
    assert issubclass(OpenApiConfigurationError, OpenApiError)
    assert issubclass(OpenApiMetadataError, OpenApiError)
    assert issubclass(OpenApiSchemaError, OpenApiError)
    assert OpenApiError("failure").diagnostic_code == "openapi.error"
    assert (
        OpenApiConfigurationError("failure").diagnostic_code
        == "openapi.configuration_error"
    )
    assert OpenApiMetadataError("failure").diagnostic_code == "openapi.metadata_error"
    assert OpenApiSchemaError("failure").diagnostic_code == "openapi.schema_error"


def test_package_artifacts_and_runtime_dependencies_are_exact() -> None:
    package_root = Path(__file__).parents[1]
    assert (package_root / "README.md").is_file()
    assert (package_root / "src/tori_py_openapi/py.typed").is_file()
    project = tomllib.loads((package_root / "pyproject.toml").read_text())
    dependencies = {
        dependency.split(">", 1)[0] for dependency in project["project"]["dependencies"]
    }
    assert dependencies == {"msgspec", "starlette", "tori-py"}


def test_import_has_no_forbidden_dependency_or_registration_side_effects() -> None:
    script = """
import sys
import tori_py_openapi

assert 'fastapi' not in sys.modules
assert 'pydantic' not in sys.modules
assert 'python_openapi' not in sys.modules
assert 'json_strong_typing' not in sys.modules
assert 'jsonschema' not in sys.modules
assert tori_py_openapi.OpenApiModule.__module__ == 'tori_py_openapi.module'
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
