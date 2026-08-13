import ast
import subprocess
import sys
from pathlib import Path

import tori_py_sqlalchemy


def test_public_api_allowlist_and_artifacts() -> None:
    assert set(tori_py_sqlalchemy.__all__) == {
        "EntityManager",
        "ExecuteParams",
        "Repository",
        "SqlAlchemyConfigurationError",
        "SqlAlchemyIntegrationError",
        "SqlAlchemyModule",
        "SqlAlchemyOptions",
        "SqlAlchemyOptionsFactory",
        "SqlAlchemySessionOptions",
        "TransactionContextError",
        "get_entity_manager_token",
        "get_engine_token",
        "get_repository_token",
        "get_session_factory_token",
        "inject_repository",
        "repository",
    }
    package_root = Path(__file__).parents[1]
    assert (package_root / "README.md").is_file()
    assert (package_root / "src/tori_py_sqlalchemy/py.typed").is_file()


def test_import_does_not_load_drivers_or_out_of_scope_integrations() -> None:
    script = """
import sys
import tori_py_sqlalchemy

for name in (
    'aiosqlite',
    'alembic',
    'asyncpg',
    'tori_py_cqrs_core',
    'tori_py_cqrs_event_sourcing_core',
    'psycopg',
    'redis',
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_runtime_imports_only_public_dependency_symbols() -> None:
    source = Path(__file__).parents[1] / "src/tori_py_sqlalchemy"
    dependency_roots = {"tori_py", "sqlalchemy"}
    for path in source.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in dependency_roots:
                    assert not any(alias.name.startswith("_") for alias in node.names)
