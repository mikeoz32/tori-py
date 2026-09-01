"""Verify the user documentation structure and public Python imports."""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"
REQUIRED_FILES = (
    "index.md",
    "404.html",
    "why-tori-py.md",
    "packages.md",
    "concepts-map.md",
    "contributing/public-api-inventory.md",
    "contributing/traceability.md",
    "getting-started/installation.md",
    "getting-started/first-application.md",
    "getting-started/project-structure.md",
    "getting-started/first-controller.md",
    "getting-started/first-provider.md",
    "getting-started/configuration.md",
    "getting-started/testing.md",
    "getting-started/next-steps.md",
    "reference/task-api.md",
    "tutorials/index.md",
    "tutorials/task-api.md",
    "tutorials/cqrs-application.md",
    "tutorials/distributed-application.md",
    "tutorials/event-sourced-application.md",
    "fundamentals/index.md",
    "fundamentals/modules.md",
    "fundamentals/providers-and-di.md",
    "fundamentals/scopes-and-resources.md",
    "fundamentals/lifecycle.md",
    "fundamentals/discovery-and-reflection.md",
    "http/index.md",
    "pipeline/index.md",
    "techniques/settings.md",
    "techniques/testing.md",
    "techniques/sqlalchemy/index.md",
    "techniques/cqrs/index.md",
    "techniques/event-sourcing/index.md",
    "techniques/microservices/index.md",
    "techniques/persistent-streams/index.md",
    "operations/index.md",
    "operations/security.md",
    "operations/limitations.md",
    "recipes/index.md",
    "reference/api.md",
    "reference/errors-and-diagnostics.md",
    "reference/examples.md",
)
PYTHON_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)
SNIPPET_DIRECTIVE = re.compile(r'^\s*--8<--\s+"([^"]+)"\s*$', re.MULTILINE)


def _check_required_files() -> list[str]:
    return [path for path in REQUIRED_FILES if not (DOCS / path).is_file()]


def _check_public_imports() -> list[str]:
    errors: list[str] = []
    for document in DOCS.rglob("*.md"):
        for snippet in PYTHON_BLOCK.findall(document.read_text(encoding="utf-8")):
            source = _snippet_source(document, snippet, errors)
            if source is None:
                continue
            try:
                tree = ast.parse(source, filename=str(document))
            except SyntaxError as error:
                errors.append(f"{document}: invalid Python snippet: {error.msg}")
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    _check_from_import(document, node, errors)
                elif isinstance(node, ast.Import):
                    _check_import(document, node, errors)
    return errors


def _snippet_source(document: Path, snippet: str, errors: list[str]) -> str | None:
    directive = SNIPPET_DIRECTIVE.fullmatch(snippet)
    if directive is None:
        return snippet
    source_file = ROOT / directive.group(1)
    if not source_file.is_file():
        errors.append(f"{document}: snippet source does not exist: {source_file}")
        return None
    return source_file.read_text(encoding="utf-8")


def _check_from_import(document: Path, node: ast.ImportFrom, errors: list[str]) -> None:
    module_name = node.module
    if module_name is None or not module_name.startswith("tori_py"):
        return
    try:
        module = importlib.import_module(module_name)
    except ImportError as error:
        errors.append(f"{document}: cannot import {module_name}: {error}")
        return
    public_symbols = getattr(module, "__all__", ())
    for imported in node.names:
        if imported.name != "*" and imported.name not in public_symbols:
            errors.append(f"{document}: {module_name}.{imported.name} is not public")


def _check_import(document: Path, node: ast.Import, errors: list[str]) -> None:
    for imported in node.names:
        if not imported.name.startswith("tori_py"):
            continue
        try:
            importlib.import_module(imported.name)
        except ImportError as error:
            errors.append(f"{document}: cannot import {imported.name}: {error}")


def main() -> None:
    errors = [
        f"missing required documentation file: {path}"
        for path in _check_required_files()
    ]
    errors.extend(_check_public_imports())
    if errors:
        raise SystemExit("\n".join(errors))


if __name__ == "__main__":
    main()
