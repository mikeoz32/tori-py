import ast
import subprocess
import sys
from pathlib import Path

import nestpy_sqlalchemy


def test_public_api_allowlist_and_artifacts() -> None:
    assert set(nestpy_sqlalchemy.__all__) == {
        "EntityManager",
        "EntityTransaction",
        "ExecuteParams",
        "SessionManager",
        "SqlAlchemyConfigurationError",
        "SqlAlchemyIntegrationError",
        "SqlAlchemyModule",
        "SqlAlchemyOptions",
        "SqlAlchemyOptionsFactory",
        "SqlAlchemySessionOptions",
        "get_entity_manager_token",
        "get_engine_token",
        "get_session_factory_token",
        "get_session_manager_token",
    }
    package_root = Path(__file__).parents[1]
    assert (package_root / "README.md").is_file()
    assert (package_root / "src/nestpy_sqlalchemy/py.typed").is_file()


def test_import_does_not_load_drivers_or_out_of_scope_integrations() -> None:
    script = """
import sys
import nestpy_sqlalchemy

for name in (
    'aiosqlite',
    'alembic',
    'asyncpg',
    'cqrs_core',
    'cqrs_event_sourcing',
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
    source = Path(__file__).parents[1] / "src/nestpy_sqlalchemy"
    dependency_roots = {"nestpy", "sqlalchemy"}
    for path in source.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".", 1)[0]
                if root in dependency_roots:
                    assert not any(alias.name.startswith("_") for alias in node.names)
