from __future__ import annotations

import tomllib
from pathlib import Path

import tori_py_liveview_ui
from tori_py_liveview_ui import (
    actions,
    content,
    conversation,
    disclosure,
    display,
    feedback,
    forms,
    icons,
    layout,
    module,
    rich_text,
)

# Each family test pins its own module's names; the facade is their union.
_FAMILIES = (
    actions,
    content,
    conversation,
    disclosure,
    display,
    feedback,
    forms,
    icons,
    layout,
    module,
    rich_text,
)


def test_public_facade_is_the_union_of_the_family_modules() -> None:
    exported = tori_py_liveview_ui.__all__
    family_names = [name for family in _FAMILIES for name in family.__all__]

    assert len(family_names) == len(set(family_names))
    assert sorted(exported) == sorted(family_names)
    assert len(exported) == len(set(exported))
    for family in _FAMILIES:
        for name in family.__all__:
            assert getattr(tori_py_liveview_ui, name) is getattr(family, name)


def test_public_facade_lists_constants_then_classes_then_helpers() -> None:
    exported = tori_py_liveview_ui.__all__
    constants = [name for name in exported if name.isupper()]
    classes = [name for name in exported if name[0].isupper() and not name.isupper()]
    helpers = [name for name in exported if name[0].islower()]

    assert exported == sorted(constants) + sorted(classes) + sorted(helpers)
    assert constants == ["SCRIPT_PATH", "STYLESHEET_PATH"]
    assert classes == ["LiveViewUiModule", "TableColumn", "UiLiveView"]


def test_foundation_families_are_explicit() -> None:
    assert icons.__all__ == ["icon"]
    assert module.__all__ == [
        "SCRIPT_PATH",
        "STYLESHEET_PATH",
        "LiveViewUiModule",
        "UiLiveView",
        "script_tag",
        "stylesheet_link",
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
    # Optional features keep their dependencies out of the required set.
    assert project["optional-dependencies"] == {
        "highlight": ["pygments>=2.17,<3"],
        "markdown": ["markdown-it-py>=3,<5"],
    }
    assert (package / "NOTICE").is_file()
    assert (package / "README.md").is_file()
    assert (package / "scripts" / "verify_artifacts.py").is_file()
    assert (package / "src" / "tori_py_liveview_ui" / "py.typed").is_file()
