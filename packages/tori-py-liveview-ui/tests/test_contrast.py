"""The bundled palettes keep text readable in both modes."""

from __future__ import annotations

import re

import pytest
from tori_py_liveview_ui import module

_AA_TEXT = 4.5
_AA_GRAPHICS = 3.0
_TONES = ("info", "success", "warning", "danger")


def _stylesheet() -> str:
    return module._STYLESHEET.decode("utf-8")


def _palette(mode: str) -> dict[str, tuple[float, float, float]]:
    match = re.search(
        r':root,\s*\[data-tori-ui-theme="paper"\]\s*\{(?P<body>.*?)\}',
        _stylesheet(),
        re.DOTALL,
    )
    assert match is not None
    index = {"light": 0, "dark": 1}[mode]
    palette: dict[str, tuple[float, float, float]] = {}
    for name, *pair in re.findall(
        r"--tori-ui-([a-z-]+):\s*light-dark\((#[0-9a-fA-F]{6}), (#[0-9a-fA-F]{6})\)",
        match.group("body"),
    ):
        value = pair[index]
        palette[name] = (
            int(value[1:3], 16) / 255,
            int(value[3:5], 16) / 255,
            int(value[5:7], 16) / 255,
        )
    return palette


def _luminance(color: tuple[float, float, float]) -> float:
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in color
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _mixed(
    color: tuple[float, float, float], ink: tuple[float, float, float], share: float
) -> tuple[float, float, float]:
    """Mix two colors as ``color-mix(in srgb, ...)`` does."""
    return (
        color[0] * share + ink[0] * (1 - share),
        color[1] * share + ink[1] * (1 - share),
        color[2] * share + ink[2] * (1 - share),
    )


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_body_and_muted_text_meet_aa_on_every_surface(mode: str) -> None:
    palette = _palette(mode)

    for surface in ("paper", "panel", "panel-raised"):
        assert _contrast(palette["ink"], palette[surface]) >= _AA_TEXT
        assert _contrast(palette["muted"], palette[surface]) >= _AA_TEXT
    assert _contrast(palette["accent-ink"], palette["accent"]) >= _AA_TEXT
    # Inverted surfaces: tooltips, pressed toggles, the connection notice.
    assert _contrast(palette["paper"], palette["ink"]) >= _AA_TEXT
    # The danger button's label.
    assert _contrast(palette["panel"], palette["danger"]) >= _AA_TEXT


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_tones_and_accent_are_visible_as_graphics_on_every_surface(mode: str) -> None:
    palette = _palette(mode)

    for name in (*_TONES, "accent"):
        for surface in ("paper", "panel"):
            assert _contrast(palette[name], palette[surface]) >= _AA_GRAPHICS


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_toned_text_mixed_with_ink_meets_aa_on_paper_and_panel(mode: str) -> None:
    palette = _palette(mode)

    for name in (*_TONES, "accent"):
        text = _mixed(palette[name], palette["ink"], 0.8)
        for surface in ("paper", "panel"):
            assert _contrast(text, palette[surface]) >= _AA_TEXT, (name, surface)


def test_text_in_a_tone_uses_the_ink_mix() -> None:
    stylesheet = _stylesheet()
    mix = "80%, var(--tori-ui-ink))"

    for selector in (
        ".tori-ui-badge--warning",
        ".tori-ui-page-header__eyebrow",
        ".tori-ui-list > li::marker",
        ":where(.tori-ui-prose) :where(li)::marker",
        ".tori-ui-stat__delta",
    ):
        rule = stylesheet[stylesheet.index(selector + " {") :]
        assert mix in rule[: rule.index("}")], selector


def test_the_mode_selects_the_palette_through_color_scheme() -> None:
    stylesheet = _stylesheet()

    for mode, scheme in (("light", "light"), ("dark", "dark"), ("auto", "light dark")):
        rule = re.search(
            rf'\[data-tori-ui-mode="{mode}"\]\s*\{{\s*'
            r"color-scheme: (?P<scheme>[a-z ]+);",
            stylesheet,
        )
        assert rule is not None, mode
        assert rule.group("scheme") == scheme
    assert "prefers-color-scheme" not in stylesheet
