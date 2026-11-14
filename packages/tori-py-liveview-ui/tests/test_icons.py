from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast, get_args
from xml.etree import ElementTree

import pytest
import tori_py_liveview_ui
from tori_py_liveview import html
from tori_py_liveview_ui import icon, icons

# Calls that break a helper's contract go through an untyped alias.
ui = cast(Any, tori_py_liveview_ui)

_SHAPES = {"circle", "ellipse", "path", "rect"}
_SHAPE_ATTRIBUTES = {"cx", "cy", "d", "height", "r", "rx", "ry", "width", "x", "y"}


def test_icon_names_and_drawings_are_the_same_closed_set() -> None:
    names = set(get_args(icons.IconName.__value__))

    assert names == set(icons.ICON_NAMES)
    assert len(names) >= 70
    for name in names:
        assert re.fullmatch(r"[a-z]+(-[a-z]+)*", name)


def test_user_guide_lists_exactly_the_bundled_icons() -> None:
    guide = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "techniques"
        / "liveview-ui"
        / "content.md"
    ).read_text(encoding="utf-8")
    table = guide.split("| Group | Names |", 1)[1]
    listed = re.findall(r"`([a-z-]+)`", table)

    assert len(listed) == len(set(listed))
    assert set(listed) == set(icons.ICON_NAMES)


def test_every_icon_is_static_geometry_without_scripts_or_references() -> None:
    for name in sorted(icons.ICON_NAMES):
        markup = html(icon(cast(Any, name))).to_html()
        root = ElementTree.fromstring(markup)

        assert root.tag == "svg"
        shapes = list(root)
        assert shapes, name
        for shape in shapes:
            assert shape.tag in _SHAPES, name
            assert set(shape.attrib) <= _SHAPE_ATTRIBUTES, name
            assert not list(shape), name
        assert "href" not in markup
        assert "url(" not in markup


def test_decorative_icon_is_hidden_from_assistive_technology() -> None:
    assert html(icon("check")).to_html() == (
        '<svg class="tori-ui-icon tori-ui-icon--md" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        'stroke-linejoin="round" focusable="false" aria-hidden="true">'
        '<path d="m5 12.5 4.5 4.5L19 7.5"/></svg>'
    )


def test_labeled_icon_is_an_image_with_an_accessible_name() -> None:
    result = html(icon("x", size="lg", label='Close "it"')).to_html()

    assert 'class="tori-ui-icon tori-ui-icon--lg"' in result
    assert 'role="img" aria-label="Close &quot;it&quot;"' in result
    assert "aria-hidden" not in result


@pytest.mark.parametrize(
    ("kwargs", "error", "message"),
    [
        ({"name": "unicorn"}, ValueError, "icon name must be one of"),
        ({"name": 1}, TypeError, "icon name must be a string"),
        ({"name": "x", "size": "xl"}, ValueError, "icon size must be one of"),
        ({"name": "x", "label": " "}, ValueError, "icon label cannot be empty"),
    ],
)
def test_icon_rejects_values_outside_its_contract(
    kwargs: dict[str, Any], error: type[Exception], message: str
) -> None:
    name = kwargs.pop("name")
    with pytest.raises(error, match=message):
        ui.icon(name, **kwargs)
