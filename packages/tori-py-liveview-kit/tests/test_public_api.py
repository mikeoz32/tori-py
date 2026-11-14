from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path

import tori_py_liveview_kit

_PACKAGE = Path(__file__).resolve().parents[1]
_EXPECTED = {
    "AssistantMessage",
    "ChatEvent",
    "ChatLiveView",
    "Citation",
    "Error",
    "Message",
    "MessagePart",
    "ReasoningDelta",
    "ReasoningPart",
    "ReplyStatus",
    "TextDelta",
    "TextPart",
    "ToolCall",
    "ToolPart",
    "ToolResult",
    "Usage",
    "UserMessage",
}


def test_facade_exports_exactly_the_documented_names() -> None:
    exported = tori_py_liveview_kit.__all__
    assert len(exported) == len(set(exported))
    assert set(exported) == _EXPECTED
    for name in exported:
        assert hasattr(tori_py_liveview_kit, name)


def test_package_is_typed() -> None:
    assert files("tori_py_liveview_kit").joinpath("py.typed").is_file()


def test_dependencies_stay_inside_the_documented_boundary() -> None:
    project = tomllib.loads((_PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    assert project["dependencies"] == [
        "tori-py-framework[cli]>=0.1.0,<0.2.0",
        "tori-py-liveview>=0.1.0,<0.2.0",
        "tori-py-liveview-ui[markdown]>=0.1.0,<0.2.0",
    ]
    assert project["optional-dependencies"] == {
        "highlight": ["tori-py-liveview-ui[highlight]>=0.1.0,<0.2.0"]
    }
