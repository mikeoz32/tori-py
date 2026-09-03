from __future__ import annotations

import tomllib
from pathlib import Path

import tori_py_liveview_ui


def test_public_facade_is_explicit() -> None:
    assert tori_py_liveview_ui.__all__ == [
        "STYLESHEET_PATH",
        "LiveViewUiModule",
        "UiLiveView",
        "alert",
        "badge",
        "button",
        "card",
        "checkbox",
        "field",
        "field_error",
        "form",
        "grid",
        "input",
        "select",
        "stack",
        "stylesheet_link",
        "textarea",
    ]


def test_distribution_metadata_preserves_package_boundaries() -> None:
    package = Path(__file__).resolve().parents[1]
    project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]

    assert project["name"] == "tori-py-liveview-ui"
    assert project["requires-python"] == ">=3.14,<3.15"
    assert project["dependencies"] == [
        "tori-py-framework>=0.1.0,<0.2.0",
        "tori-py-liveview>=0.1.0,<0.2.0",
    ]
    assert (package / "NOTICE").is_file()
    assert (package / "README.md").is_file()
    assert (package / "scripts" / "verify_artifacts.py").is_file()
    assert (package / "src" / "tori_py_liveview_ui" / "py.typed").is_file()
