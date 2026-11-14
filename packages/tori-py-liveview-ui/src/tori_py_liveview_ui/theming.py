"""Typed theme and skin definitions and the CSS generated from them.

A theme is a pair of palettes, one for the light and one for the dark color
mode. A skin is everything about shape: spacing, radii, control geometry,
typography, shadows, and focus. The fields of ``Palette`` and ``Skin`` are the
public token contract: the field ``radius_control`` is the custom property
``--tori-ui-radius-control``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import KW_ONLY, dataclass
from functools import lru_cache
from typing import Any, ClassVar, Literal

from tori_py_liveview_ui import _color

type ColorMode = Literal["light", "dark"]
type TextCase = Literal["none", "uppercase", "lowercase", "capitalize"]

_ASSET_PREFIX = "/_tori/liveview-ui/"
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}")
_UNITS = "rem|em|px|%|ch|vw|vh"
_SIZE = re.compile(rf"0|(?:\d+|\d*\.\d+)(?:{_UNITS})")
_OFFSET = re.compile(rf"0|-?(?:\d+|\d*\.\d+)(?:{_UNITS})")
_FAMILY = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
_GENERIC_FAMILIES = frozenset(
    {
        "cursive",
        "emoji",
        "fangsong",
        "fantasy",
        "math",
        "monospace",
        "sans-serif",
        "serif",
        "system-ui",
        "ui-monospace",
        "ui-rounded",
        "ui-sans-serif",
        "ui-serif",
    }
)
_CASES = ("none", "uppercase", "lowercase", "capitalize")
_AA_TEXT = 4.5
_AA_GRAPHICS = 3.0
# The share of a tone in text set in that tone; the rest is the ink. The
# stylesheet mixes the same way, with color-mix().
_TONE_TEXT_SHARE = 0.8
_TONES = ("info", "success", "warning", "danger")
_SURFACES = ("paper", "panel", "panel_raised")
_TRANSLUCENT = frozenset({"shadow_color", "scrim"})
_SHADOW = (
    "var(--tori-ui-shadow-x) var(--tori-ui-shadow-y) var(--tori-ui-shadow-blur) "
    "var(--tori-ui-shadow-spread) var(--tori-ui-shadow-color)"
)
_RADIUS_SURFACE_INNER = (
    "max(0px, calc(var(--tori-ui-radius-surface) - var(--tori-ui-border-width)))"
)


# ------------------------------------------------------------- Value kinds


def _definition_name(kind: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{kind} name must be a string")
    if _NAME.fullmatch(value) is None:
        raise ValueError(f"{kind} name must match [a-z][a-z0-9-]{{0,63}}")
    return value


def _size(label: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if _SIZE.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be 0 or a length in rem, em, px, %, ch, vw, or vh"
        )
    return value


def _offset(label: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if _OFFSET.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be 0 or a signed length in rem, em, px, %, ch, vw, or vh"
        )
    return value


def _box(label: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    parts = value.split(" ")
    if not 1 <= len(parts) <= 4 or any(_SIZE.fullmatch(part) is None for part in parts):
        raise ValueError(f"{label} must be one to four lengths separated by spaces")
    return value


def _font_stack(label: str, value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, Iterable):
        raise TypeError(f"{label} must be a tuple of font family names")
    families: list[str] = []
    for family in value:
        if not isinstance(family, str):
            raise TypeError(f"{label} must be a tuple of font family names")
        families.append(family)
    if not 1 <= len(families) <= 12:
        raise ValueError(f"{label} must name one to twelve font families")
    for family in families:
        if _FAMILY.fullmatch(family) is None:
            raise ValueError(
                f"{label} family names may hold letters, digits, spaces, dots, "
                "underscores, and hyphens"
            )
    return tuple(families)


def _weight(label: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    if not 1 <= value <= 1000:
        raise ValueError(f"{label} must be from 1 to 1000")
    return value


def _case(label: str, value: object) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if value not in _CASES:
        raise ValueError(f"{label} must be one of: {', '.join(_CASES)}")
    return value


def _opacity(label: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{label} must be a number")
    if not 0 <= value <= 1:
        raise ValueError(f"{label} must be from 0 to 1")
    return float(value)


def _css_value(value: object) -> str:
    if isinstance(value, tuple):
        families = [str(family) for family in value]
        return ", ".join(
            family.lower() if family.lower() in _GENERIC_FAMILIES else f'"{family}"'
            for family in families
        )
    if isinstance(value, float):
        return format(value, "g")
    return str(value)


def _rule(selector: str, declarations: Iterable[tuple[str, str]]) -> str:
    body = "".join(
        f"  --tori-ui-{token.replace('_', '-')}: {value};\n"
        for token, value in declarations
    )
    return f"{selector} {{\n{body}}}\n"


# ------------------------------------------------------------------ Themes


@dataclass(frozen=True, slots=True, kw_only=True)
class Palette:
    """The colors of a theme in one color mode.

    Every color is ``#rgb``, ``#rrggbb``, or ``#rrggbbaa``. Only
    ``shadow_color`` and ``scrim`` may be translucent.
    """

    paper: str
    panel: str
    panel_raised: str
    ink: str
    muted: str
    line: str
    line_strong: str
    accent: str
    accent_ink: str
    danger: str
    info: str
    success: str
    warning: str
    shadow_color: str
    scrim: str

    def __post_init__(self) -> None:
        for token in _PALETTE_TOKENS:
            color = _color.normalize(
                f"palette {token}",
                getattr(self, token),
                opaque=token not in _TRANSLUCENT,
            )
            object.__setattr__(self, token, color)

    def derive(self, **changes: Any) -> Palette:
        """Return a copy of the palette with some colors changed."""
        _reject_unknown("palette", changes, _PALETTE_TOKENS)
        return dataclasses.replace(self, **changes)

    def tokens(self) -> dict[str, str]:
        """Return each token name, as in the custom property, with its color."""
        return {
            token.replace("_", "-"): getattr(self, token) for token in _PALETTE_TOKENS
        }


_PALETTE_TOKENS = tuple(field.name for field in dataclasses.fields(Palette))


@dataclass(frozen=True, slots=True)
class ContrastCheck:
    """One contrast requirement of a theme and the ratio the theme reaches."""

    mode: ColorMode
    foreground: str
    background: str
    ratio: float
    required: float

    @property
    def passes(self) -> bool:
        return self.ratio >= self.required


class ThemeContrastError(ValueError):
    """A theme whose colors do not reach the contrast the stylesheet needs."""

    def __init__(self, theme: str, failures: tuple[ContrastCheck, ...]) -> None:
        self.theme = theme
        self.failures = failures
        pairs = "; ".join(
            f"{check.mode} {check.foreground} on {check.background} is "
            f"{check.ratio:.2f}:1 and needs {check.required:g}:1"
            for check in failures
        )
        super().__init__(
            f"theme {theme!r} does not reach the required contrast: {pairs}. "
            "Change the colors, or pass allow_low_contrast=True to build it anyway."
        )


@dataclass(frozen=True, slots=True)
class Theme:
    """A named pair of palettes: one for the light mode and one for the dark."""

    name: str
    _: KW_ONLY
    light: Palette
    dark: Palette
    allow_low_contrast: bool = False

    PAPER: ClassVar[Theme]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _definition_name("theme", self.name))
        for mode in ("light", "dark"):
            if not isinstance(getattr(self, mode), Palette):
                raise TypeError(f"theme {mode} must be a Palette")
        if not isinstance(self.allow_low_contrast, bool):
            raise TypeError("theme allow_low_contrast must be a bool")
        if not self.allow_low_contrast:
            failures = tuple(check for check in self.report() if not check.passes)
            if failures:
                raise ThemeContrastError(self.name, failures)

    def report(self) -> tuple[ContrastCheck, ...]:
        """Return every contrast requirement with the ratio this theme reaches."""
        return (
            *_contrast_checks("light", self.light),
            *_contrast_checks("dark", self.dark),
        )

    def tokens(self) -> dict[str, str]:
        """Return each palette token with its ``light-dark()`` pair."""
        light = self.light.tokens()
        dark = self.dark.tokens()
        return {token: f"light-dark({light[token]}, {dark[token]})" for token in light}

    def css(self) -> str:
        """Return the rule that defines this theme's tokens."""
        return _theme_rule(f'[data-tori-ui-theme="{self.name}"]', self)

    @property
    def stylesheet_path(self) -> str:
        """The content-addressed path that serves this theme once registered."""
        return _stylesheet(self)[0]


def _theme_rule(selector: str, theme: Theme) -> str:
    # The composed shadow is declared again so that a theme on an inner
    # element composes it with its own shadow color.
    return _rule(selector, (*theme.tokens().items(), ("shadow", _SHADOW)))


def _contrast_checks(mode: ColorMode, palette: Palette) -> list[ContrastCheck]:
    colors = {
        token: _color.rgb(getattr(palette, token))
        for token in _PALETTE_TOKENS
        if token not in _TRANSLUCENT
    }
    checks: list[ContrastCheck] = []

    def check(
        foreground: str,
        background: str,
        required: float,
        *,
        color: _color.Rgb | None = None,
        label: str | None = None,
    ) -> None:
        ratio = _color.contrast(
            colors[foreground] if color is None else color, colors[background]
        )
        checks.append(
            ContrastCheck(mode, label or foreground, background, ratio, required)
        )

    for surface in _SURFACES:
        check("ink", surface, _AA_TEXT)
        check("muted", surface, _AA_TEXT)
    check("accent_ink", "accent", _AA_TEXT)
    # The label of a danger button.
    check("panel", "danger", _AA_TEXT)
    for tone in (*_TONES, "accent"):
        text = _color.mix(colors[tone], colors["ink"], _TONE_TEXT_SHARE)
        for surface in ("paper", "panel"):
            check(tone, surface, _AA_GRAPHICS)
            check(tone, surface, _AA_TEXT, color=text, label=f"{tone} text")
    return checks


# ------------------------------------------------------------------- Skins


@dataclass(frozen=True, slots=True)
class Skin:
    """A named shape: spacing, radii, control geometry, type, shadow, focus.

    Sizes are ``0`` or a number with ``rem``, ``em``, ``px``, ``%``, ``ch``,
    ``vw``, or ``vh``; offsets may be negative; paddings take one to four
    sizes. Start from a bundled skin with ``derive()``.
    """

    name: str
    _: KW_ONLY
    space_xs: str
    space_sm: str
    space_md: str
    space_lg: str
    space_xl: str
    radius_control: str
    radius_surface: str
    radius_pill: str
    control_height_sm: str
    control_height_md: str
    control_height_lg: str
    field_control_height: str
    control_padding_block: str
    control_padding_inline: str
    button_padding_sm: str
    button_padding_lg: str
    alert_padding: str
    card_header_padding: str
    card_body_padding: str
    card_footer_padding: str
    form_gap: str
    field_gap: str
    field_control_radius: str
    field_control_padding_block: str
    field_control_padding_inline: str
    border_width: str
    accent_border_width: str
    font_display: tuple[str, ...]
    font_body: tuple[str, ...]
    font_code: tuple[str, ...]
    control_font_weight: int
    control_letter_spacing: str
    control_text_transform: TextCase
    label_font_weight: int
    label_letter_spacing: str
    label_text_transform: TextCase
    shadow_x: str
    shadow_y: str
    shadow_blur: str
    shadow_spread: str
    focus_width: str
    focus_offset: str
    field_focus_offset: str
    disabled_opacity: float
    field_disabled_opacity: float
    grid_min: str
    checkbox_size: str
    checkbox_gap: str
    hover_translate: str

    EDITORIAL: ClassVar[Skin]
    MINIMAL: ClassVar[Skin]
    ROUNDED: ClassVar[Skin]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _definition_name("skin", self.name))
        for token, kind in _SKIN_KINDS.items():
            value = kind(f"skin {token}", getattr(self, token))
            object.__setattr__(self, token, value)

    def derive(self, name: str, /, **changes: Any) -> Skin:
        """Return a copy of the skin under a new name with some tokens changed."""
        _reject_unknown("skin", changes, _SKIN_KINDS)
        return dataclasses.replace(self, name=name, **changes)

    def tokens(self) -> dict[str, str]:
        """Return each token name, as in the custom property, with its value."""
        return {
            token.replace("_", "-"): _css_value(getattr(self, token))
            for token in _SKIN_KINDS
        }

    def css(self) -> str:
        """Return the rule that defines this skin's tokens."""
        return _skin_rule(f'[data-tori-ui-skin="{self.name}"]', self)

    @property
    def stylesheet_path(self) -> str:
        """The content-addressed path that serves this skin once registered."""
        return _stylesheet(self)[0]


def _skin_rule(selector: str, skin: Skin) -> str:
    # The composed tokens are declared in every skin so that a skin on an
    # inner element composes them from its own parts.
    return _rule(
        selector,
        (
            *skin.tokens().items(),
            ("radius-surface-inner", _RADIUS_SURFACE_INNER),
            ("shadow", _SHADOW),
        ),
    )


_SKIN_KINDS: dict[str, Callable[[str, object], object]] = {
    "space_xs": _size,
    "space_sm": _size,
    "space_md": _size,
    "space_lg": _size,
    "space_xl": _size,
    "radius_control": _size,
    "radius_surface": _size,
    "radius_pill": _size,
    "control_height_sm": _size,
    "control_height_md": _size,
    "control_height_lg": _size,
    "field_control_height": _size,
    "control_padding_block": _size,
    "control_padding_inline": _size,
    "button_padding_sm": _box,
    "button_padding_lg": _box,
    "alert_padding": _box,
    "card_header_padding": _box,
    "card_body_padding": _box,
    "card_footer_padding": _box,
    "form_gap": _size,
    "field_gap": _size,
    "field_control_radius": _size,
    "field_control_padding_block": _size,
    "field_control_padding_inline": _size,
    "border_width": _size,
    "accent_border_width": _size,
    "font_display": _font_stack,
    "font_body": _font_stack,
    "font_code": _font_stack,
    "control_font_weight": _weight,
    "control_letter_spacing": _offset,
    "control_text_transform": _case,
    "label_font_weight": _weight,
    "label_letter_spacing": _offset,
    "label_text_transform": _case,
    "shadow_x": _offset,
    "shadow_y": _offset,
    "shadow_blur": _size,
    "shadow_spread": _offset,
    "focus_width": _size,
    "focus_offset": _offset,
    "field_focus_offset": _offset,
    "disabled_opacity": _opacity,
    "field_disabled_opacity": _opacity,
    "grid_min": _size,
    "checkbox_size": _size,
    "checkbox_gap": _size,
    "hover_translate": _offset,
}


@lru_cache(maxsize=256)
def _stylesheet(definition: Theme | Skin) -> tuple[str, bytes]:
    """Return the path and the bytes of a definition's own stylesheet."""
    kind = "theme" if isinstance(definition, Theme) else "skin"
    body = definition.css().encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    return f"{_ASSET_PREFIX}{kind}-{definition.name}.{digest[:12]}.css", body


def _reject_unknown(kind: str, changes: dict[str, Any], known: Iterable[str]) -> None:
    unknown = sorted(set(changes) - set(known))
    if unknown:
        raise TypeError(f"unknown {kind} tokens: {', '.join(unknown)}")


# ------------------------------------------------------ Bundled definitions

Theme.PAPER = Theme(
    "paper",
    light=Palette(
        paper="#f2ecdf",
        panel="#fffdf7",
        panel_raised="#fffaf0",
        ink="#20201d",
        muted="#6e675d",
        line="#cfc4b3",
        line_strong="#393630",
        accent="#c43f27",
        accent_ink="#fffaf2",
        danger="#94291f",
        info="#176b87",
        success="#2f7450",
        warning="#9a640b",
        shadow_color="#2d241829",
        scrim="#201c1680",
    ),
    dark=Palette(
        paper="#191816",
        panel="#26231f",
        panel_raised="#302b25",
        ink="#f4eddf",
        muted="#c2b7a8",
        line="#514a40",
        line_strong="#e7dccb",
        accent="#ff7458",
        accent_ink="#241713",
        danger="#ff8a74",
        info="#72cbe7",
        success="#79d3a1",
        warning="#efbd5c",
        shadow_color="#0000006b",
        scrim="#0000009e",
    ),
)

Skin.EDITORIAL = Skin(
    "editorial",
    space_xs="0.25rem",
    space_sm="0.5rem",
    space_md="1rem",
    space_lg="1.5rem",
    space_xl="2.5rem",
    radius_control="0.28rem",
    radius_surface="0",
    radius_pill="999px",
    control_height_sm="2rem",
    control_height_md="2.5rem",
    control_height_lg="3rem",
    field_control_height="2.75rem",
    control_padding_block="0.7rem",
    control_padding_inline="1rem",
    button_padding_sm="0.5rem 0.72rem",
    button_padding_lg="0.9rem 1.25rem",
    alert_padding="1rem 1.1rem",
    card_header_padding="1.15rem 1.2rem 0.95rem",
    card_body_padding="1.2rem",
    card_footer_padding="0.75rem 1.2rem",
    form_gap="1.15rem",
    field_gap="0.42rem",
    field_control_radius="0.22rem",
    field_control_padding_block="0.68rem",
    field_control_padding_inline="0.75rem",
    border_width="1px",
    accent_border_width="5px",
    font_display=(
        "Iowan Old Style",
        "Palatino Linotype",
        "Book Antiqua",
        "Georgia",
        "serif",
    ),
    font_body=(
        "Avenir Next",
        "Avenir",
        "Century Gothic",
        "Trebuchet MS",
        "sans-serif",
    ),
    font_code=("Cascadia Code", "IBM Plex Mono", "Consolas", "monospace"),
    control_font_weight=750,
    control_letter_spacing="0.075em",
    control_text_transform="uppercase",
    label_font_weight=700,
    label_letter_spacing="0.055em",
    label_text_transform="uppercase",
    shadow_x="4px",
    shadow_y="4px",
    shadow_blur="0",
    shadow_spread="0",
    focus_width="3px",
    focus_offset="3px",
    field_focus_offset="2px",
    disabled_opacity=0.46,
    field_disabled_opacity=0.52,
    grid_min="16rem",
    checkbox_size="1.15rem",
    checkbox_gap="0.65rem",
    hover_translate="-1px",
)

Skin.MINIMAL = Skin.EDITORIAL.derive(
    "minimal",
    space_xs="0.2rem",
    space_sm="0.4rem",
    space_md="0.8rem",
    space_lg="1.2rem",
    space_xl="2rem",
    radius_control="0.15rem",
    radius_surface="0.15rem",
    control_height_sm="1.9rem",
    control_height_md="2.35rem",
    control_height_lg="2.75rem",
    field_control_height="2.55rem",
    control_padding_block="0.6rem",
    control_padding_inline="0.85rem",
    button_padding_sm="0.4rem 0.6rem",
    button_padding_lg="0.75rem 1.1rem",
    alert_padding="0.8rem",
    card_header_padding="0.8rem",
    card_body_padding="0.8rem",
    card_footer_padding="0.4rem 0.8rem",
    form_gap="0.8rem",
    field_gap="0.4rem",
    field_control_radius="0.15rem",
    field_control_padding_block="0.6rem",
    field_control_padding_inline="0.75rem",
    accent_border_width="3px",
    font_display=("ui-sans-serif", "system-ui", "sans-serif"),
    font_body=("ui-sans-serif", "system-ui", "sans-serif"),
    font_code=("ui-monospace", "Cascadia Code", "Consolas", "monospace"),
    control_font_weight=650,
    control_letter_spacing="0.01em",
    control_text_transform="none",
    label_font_weight=650,
    label_letter_spacing="0.01em",
    label_text_transform="none",
    shadow_x="0",
    shadow_y="1px",
    shadow_blur="2px",
    shadow_spread="0",
    focus_offset="2px",
    field_focus_offset="2px",
    disabled_opacity=0.5,
    field_disabled_opacity=0.5,
    grid_min="15rem",
    checkbox_size="1.05rem",
    checkbox_gap="0.4rem",
    hover_translate="0",
)

Skin.ROUNDED = Skin.EDITORIAL.derive(
    "rounded",
    space_xs="0.3rem",
    space_sm="0.65rem",
    space_md="1.1rem",
    space_lg="1.75rem",
    space_xl="2.75rem",
    radius_control="0.75rem",
    radius_surface="1rem",
    control_height_sm="2.25rem",
    control_height_md="2.75rem",
    control_height_lg="3.25rem",
    field_control_height="3rem",
    control_padding_block="0.72rem",
    control_padding_inline="1.05rem",
    button_padding_sm="0.6rem 0.85rem",
    button_padding_lg="0.95rem 1.35rem",
    alert_padding="1.1rem 1.25rem",
    card_header_padding="1.2rem 1.35rem",
    card_body_padding="1.25rem 1.35rem",
    card_footer_padding="0.65rem 1.35rem",
    form_gap="1.1rem",
    field_gap="0.65rem",
    field_control_radius="0.75rem",
    field_control_padding_block="0.72rem",
    field_control_padding_inline="0.9rem",
    accent_border_width="4px",
    font_display=("ui-rounded", "Avenir Next", "system-ui", "sans-serif"),
    font_body=("Avenir Next", "system-ui", "sans-serif"),
    font_code=("ui-monospace", "Cascadia Code", "Consolas", "monospace"),
    control_font_weight=700,
    control_letter_spacing="0.015em",
    control_text_transform="none",
    label_font_weight=700,
    label_letter_spacing="0.025em",
    label_text_transform="none",
    shadow_x="0",
    shadow_y="12px",
    shadow_blur="32px",
    shadow_spread="-20px",
    focus_offset="3px",
    field_focus_offset="3px",
    disabled_opacity=0.48,
    field_disabled_opacity=0.48,
    grid_min="17rem",
    checkbox_size="1.2rem",
    checkbox_gap="0.65rem",
    hover_translate="-1px",
)

_BUNDLED_THEMES: tuple[Theme, ...] = (Theme.PAPER,)
_BUNDLED_SKINS: tuple[Skin, ...] = (Skin.EDITORIAL, Skin.MINIMAL, Skin.ROUNDED)
_MODE_SCHEMES = (("light", "light"), ("dark", "dark"), ("auto", "light dark"))


def _bundled_css() -> str:
    """Return the token rules of the bundled definitions.

    The first theme and the first skin are also the defaults of a document
    that sets no attribute.
    """
    default_theme, *themes = _BUNDLED_THEMES
    default_skin, *skins = _BUNDLED_SKINS
    modes = "\n".join(
        f'[data-tori-ui-mode="{mode}"] {{\n  color-scheme: {scheme};\n}}\n'
        for mode, scheme in _MODE_SCHEMES
    )
    rules = [
        "/* Tokens generated from the bundled theme and skin definitions. */\n",
        _theme_rule(
            f':root,\n[data-tori-ui-theme="{default_theme.name}"]', default_theme
        ),
        *(theme.css() for theme in themes),
        "/* The mode picks the palette: light-dark() follows color-scheme. */\n"
        + modes,
        _skin_rule(f':root,\n[data-tori-ui-skin="{default_skin.name}"]', default_skin),
        *(skin.css() for skin in skins),
    ]
    return "\n".join(rules) + "\n"


__all__ = [
    "ContrastCheck",
    "Palette",
    "Skin",
    "Theme",
    "ThemeContrastError",
]
