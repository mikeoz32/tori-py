"""The helpers and the stylesheet agree on class names."""

from __future__ import annotations

import re
from importlib.resources import files
from pathlib import Path

import tori_py_liveview_ui

_SOURCES = Path(tori_py_liveview_ui.__file__).parent
_CLASS = re.compile(r"tori-ui-[a-z0-9_-]*")

# Classes that only name a part of the markup and take no rule of their own.
_UNSTYLED = {
    "tori-ui-center--content",
    "tori-ui-container--lg",
    "tori-ui-divider__label",
    "tori-ui-image--auto",
    "tori-ui-list--number",
    "tori-ui-page-header__heading",
    "tori-ui-page-header__navigation",
    "tori-ui-section__heading",
    "tori-ui-split--1-1",
    "tori-ui-text--md",
}


def _stylesheet() -> str:
    return (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )


def _source_classes() -> tuple[set[str], set[str]]:
    exact: set[str] = set()
    prefixes: set[str] = set()
    for path in _SOURCES.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        # Attribute names such as data-tori-ui-confirm are not classes.
        source = re.sub(r"data-tori-ui-[a-z-]*", "", source)
        for name in _CLASS.findall(source):
            if name == "tori-ui-":
                continue
            # An f-string builds the rest of a name that ends in a hyphen.
            (prefixes if name.endswith("-") else exact).add(name)
    return exact, prefixes


def test_every_class_a_helper_emits_has_a_rule_or_is_listed_as_unstyled() -> None:
    stylesheet = _stylesheet()
    styled = set(re.findall(r"\.(tori-ui-[a-z0-9_-]+)", stylesheet))
    exact, prefixes = _source_classes()

    assert exact - styled - _UNSTYLED == set()
    for prefix in prefixes:
        assert any(name.startswith(prefix) for name in styled), prefix
    # The list of unstyled names stays honest.
    assert _UNSTYLED & styled == set()
    assert _UNSTYLED <= exact | {
        name for name in _UNSTYLED if name.startswith(tuple(prefixes))
    }


def test_every_rule_belongs_to_a_class_a_helper_emits() -> None:
    styled = set(re.findall(r"\.(tori-ui-[a-z0-9_-]+)", _stylesheet()))
    exact, prefixes = _source_classes()
    # The LiveView client and the script set these, not the helpers.
    set_in_the_browser = {"tori-ui-document"}

    orphans = {
        name
        for name in styled - exact - set_in_the_browser
        if not name.startswith(tuple(prefixes))
    }
    assert orphans == set()


def test_keyframes_and_custom_properties_are_prefixed() -> None:
    stylesheet = _stylesheet()

    for name in re.findall(r"@keyframes\s+([a-z0-9-]+)", stylesheet):
        assert name.startswith("tori-ui-")
    for name in re.findall(r"(?<![a-z0-9-])--([a-z0-9-]+)\s*:", stylesheet):
        assert name.startswith("tori-ui-")
    assert "!important" not in stylesheet
