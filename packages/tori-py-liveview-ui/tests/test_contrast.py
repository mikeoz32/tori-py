"""The bundled palettes keep text readable in both themes."""

from __future__ import annotations

import re
from importlib.resources import files

import pytest

_AA_TEXT = 4.5
_AA_GRAPHICS = 3.0
_TONES = ("info", "success", "warning", "danger")


def _stylesheet() -> str:
    return (
        files("tori_py_liveview_ui")
        .joinpath("static", "tori_liveview_ui.css")
        .read_text(encoding="utf-8")
    )


def _palette(theme: str) -> dict[str, tuple[float, float, float]]:
    pattern = {
        "light": r':root,\s*\[data-tori-ui-theme="light"\].*?\{(?P<body>.*?)\}',
        "dark": r'\n\[data-tori-ui-theme="dark"\]\s*\{(?P<body>.*?)\}',
    }[theme]
    match = re.search(pattern, _stylesheet(), re.DOTALL)
    assert match is not None
    return {
        name: (
            int(value[1:3], 16) / 255,
            int(value[3:5], 16) / 255,
            int(value[5:7], 16) / 255,
        )
        for name, value in re.findall(
            r"--tori-ui-([a-z-]+):\s*(#[0-9a-fA-F]{6})", match.group("body")
        )
    }


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


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_body_and_muted_text_meet_aa_on_every_surface(theme: str) -> None:
    palette = _palette(theme)

    for surface in ("paper", "panel", "panel-raised"):
        assert _contrast(palette["ink"], palette[surface]) >= _AA_TEXT
        assert _contrast(palette["muted"], palette[surface]) >= _AA_TEXT
    assert _contrast(palette["accent-ink"], palette["accent"]) >= _AA_TEXT
    # Inverted surfaces: tooltips, pressed toggles, the connection notice.
    assert _contrast(palette["paper"], palette["ink"]) >= _AA_TEXT
    # The danger button's label.
    assert _contrast(palette["panel"], palette["danger"]) >= _AA_TEXT


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_tones_and_accent_are_visible_as_graphics_on_every_surface(theme: str) -> None:
    palette = _palette(theme)

    for name in (*_TONES, "accent"):
        for surface in ("paper", "panel"):
            assert _contrast(palette[name], palette[surface]) >= _AA_GRAPHICS


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_toned_text_mixed_with_ink_meets_aa_on_paper_and_panel(theme: str) -> None:
    palette = _palette(theme)

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


def test_the_auto_theme_repeats_the_dark_palette() -> None:
    stylesheet = _stylesheet()
    automatic = re.search(
        r'@media \(prefers-color-scheme: dark\) \{\s*\[data-tori-ui-theme="auto"\]'
        r"\s*\{(?P<body>.*?)\}",
        stylesheet,
        re.DOTALL,
    )
    dark = re.search(
        r'\n\[data-tori-ui-theme="dark"\]\s*\{(?P<body>.*?)\}', stylesheet, re.DOTALL
    )
    assert automatic is not None
    assert dark is not None

    def declarations(body: str) -> list[str]:
        return [line.strip() for line in body.strip().splitlines()]

    assert declarations(automatic.group("body")) == declarations(dark.group("body"))
