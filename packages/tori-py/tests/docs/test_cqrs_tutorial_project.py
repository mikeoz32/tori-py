from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TUTORIAL_SOURCE = (
    ROOT / "examples" / "tori_py" / "tutorials" / "cqrs_task_api" / "task_app"
)


def test_cqrs_tutorial_runs_as_an_isolated_project(tmp_path: Path) -> None:
    project = tmp_path / "cqrs-task-api"
    uv = shutil.which("uv")
    assert uv is not None

    _run(uv, "init", "--python", "3.14", "--bare", str(project), cwd=tmp_path)
    _run(uv, "python", "pin", "3.14", cwd=project)
    (project / "pyproject.toml").write_text(
        _project_metadata(),
        encoding="utf-8",
    )
    _run(
        uv,
        "add",
        "--editable",
        f"{ROOT / 'packages' / 'tori-py'}[cli,testing]",
        cwd=project,
    )
    _run(
        uv,
        "add",
        "--editable",
        str(ROOT / "packages" / "tori-py-cqrs-core"),
        cwd=project,
    )
    _run(
        uv,
        "add",
        "--editable",
        str(ROOT / "packages" / "tori-py-cqrs"),
        cwd=project,
    )
    _run(uv, "add", "--dev", "pytest", "pytest-asyncio", cwd=project)

    shutil.copytree(
        TUTORIAL_SOURCE,
        project / "task_app",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    result = _run(
        uv,
        "run",
        "pytest",
        "task_app/test_app.py",
        "-q",
        cwd=project,
    )

    assert "2 passed" in result.stdout
    assert (project / ".python-version").read_text(encoding="utf-8") == "3.14\n"
    assert 'requires-python = ">=3.14,<3.15"' in (project / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def _project_metadata() -> str:
    return """[project]
name = "cqrs-task-api"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = []
"""


def _run(
    uv: str,
    *arguments: str,
    cwd: Path,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [uv, *arguments],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result
