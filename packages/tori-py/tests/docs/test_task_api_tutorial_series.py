from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
TUTORIALS = ROOT / "examples" / "tori_py" / "tutorials"
PART_ONE = TUTORIALS / "task_api" / "task_app"
PART_TWO = TUTORIALS / "cqrs_task_api" / "task_app"
PART_THREE = TUTORIALS / "distributed_task_api" / "task_app"
PART_FOUR = TUTORIALS / "event_sourced_task_api" / "task_app"


def test_task_tutorial_series_runs_as_an_isolated_project(tmp_path: Path) -> None:
    project = tmp_path / "task-api"
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
    _run(uv, "add", "--dev", "pytest", "pytest-asyncio", cwd=project)

    _replace_application(PART_ONE, project)
    part_one = _run(
        uv,
        "run",
        "pytest",
        "task_app/test_app.py",
        "-q",
        cwd=project,
    )
    assert "2 passed" in part_one.stdout

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
    _replace_application(PART_TWO, project)
    part_two = _run(
        uv,
        "run",
        "pytest",
        "task_app/test_app.py",
        "-q",
        cwd=project,
    )
    assert "3 passed" in part_two.stdout

    _run(
        uv,
        "add",
        "--editable",
        f"{ROOT / 'packages' / 'tori-py-microservices'}[rabbitmq]",
        cwd=project,
    )
    _replace_application(PART_THREE, project)
    part_three = _run(
        uv,
        "run",
        "pytest",
        "task_app/test_system.py",
        "-q",
        cwd=project,
    )

    assert "1 passed" in part_three.stdout

    for package in (
        "tori-py-cqrs-event-sourcing-core",
        "tori-py-cqrs-event-sourcing",
        "tori-py-persistent-streams-core",
        "tori-py-persistent-streams",
        "tori-py-persistent-streams-rabbitmq",
    ):
        _run(
            uv,
            "add",
            "--editable",
            str(ROOT / "packages" / package),
            cwd=project,
        )
    _replace_application(PART_FOUR, project)
    part_four = _run(
        uv,
        "run",
        "pytest",
        "task_app",
        "-q",
        cwd=project,
    )

    assert "31 passed" in part_four.stdout
    assert (project / ".python-version").read_text(encoding="utf-8") == "3.14\n"
    assert 'requires-python = ">=3.14,<3.15"' in (project / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def _project_metadata() -> str:
    return """[project]
name = "task-api"
version = "0.1.0"
requires-python = ">=3.14,<3.15"
dependencies = []
"""


def _replace_application(source: Path, project: Path) -> None:
    destination = project / "task_app"
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


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
