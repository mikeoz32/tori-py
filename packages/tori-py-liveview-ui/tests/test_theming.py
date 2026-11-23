"""Theme and skin definitions validate their values and generate CSS."""

from __future__ import annotations

import dataclasses

import pytest
import tori_py_liveview_ui as ui
from tori_py_liveview import html
from tori_py_liveview_ui import (
    ContrastCheck,
    Palette,
    Skin,
    Theme,
    ThemeContrastError,
    themed,
    theming,
)

LIGHT = Theme.PAPER.light
DARK = Theme.PAPER.dark


def test_theming_names_are_explicit() -> None:
    assert theming.__all__ == [
        "ContrastCheck",
        "Palette",
        "Skin",
        "Theme",
        "ThemeContrastError",
        "themed",
    ]
    for name in theming.__all__:
        assert getattr(ui, name) is getattr(theming, name)


# ----------------------------------------------------------------- Palette


def test_palette_normalizes_its_colors() -> None:
    palette = LIGHT.derive(paper="#FFF", accent="#C43F27FF", scrim="#00000080")

    assert palette.paper == "#ffffff"
    # A fully opaque eight-digit color is the six-digit color.
    assert palette.accent == "#c43f27"
    assert palette.scrim == "#00000080"
    assert palette.ink == LIGHT.ink


@pytest.mark.parametrize(
    "value",
    ["red", "rgb(0 0 0)", "#12", "#12345", "#ggg", "#fff; color: red", "var(--x)"],
)
def test_palette_rejects_values_that_are_not_hex_colors(value: str) -> None:
    with pytest.raises(ValueError, match="palette paper must be a #rgb"):
        LIGHT.derive(paper=value)


def test_palette_rejects_values_that_are_not_strings() -> None:
    with pytest.raises(TypeError, match="palette ink must be a string"):
        LIGHT.derive(ink=0x20201D)


def test_only_the_shadow_and_the_scrim_may_be_translucent() -> None:
    with pytest.raises(ValueError, match="palette ink must be an opaque color"):
        LIGHT.derive(ink="#20201d80")

    assert LIGHT.derive(shadow_color="#00000033").shadow_color == "#00000033"


def test_palette_derive_rejects_unknown_tokens() -> None:
    with pytest.raises(TypeError, match="unknown palette tokens: brand, glow"):
        LIGHT.derive(glow="#fff", brand="#000")


def test_palette_tokens_carry_the_custom_property_names() -> None:
    tokens = LIGHT.tokens()

    assert list(tokens) == [
        "paper",
        "panel",
        "panel-raised",
        "ink",
        "muted",
        "line",
        "line-strong",
        "accent",
        "accent-ink",
        "danger",
        "info",
        "success",
        "warning",
        "shadow-color",
        "scrim",
    ]
    assert tokens["panel-raised"] == "#fffaf0"


def test_definitions_are_immutable() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        LIGHT.paper = "#ffffff"  # ty: ignore[invalid-assignment]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Theme.PAPER.name = "other"  # ty: ignore[invalid-assignment]
    with pytest.raises(dataclasses.FrozenInstanceError):
        Skin.EDITORIAL.space_md = "2rem"  # ty: ignore[invalid-assignment]


# ------------------------------------------------------------------- Theme


@pytest.mark.parametrize(
    "name", ["", "Paper", "two words", "-leading", "a" * 65, 'x"]{}']
)
def test_theme_rejects_names_that_are_not_css_identifiers(name: str) -> None:
    with pytest.raises(ValueError, match="theme name must match"):
        Theme(name, light=LIGHT, dark=DARK)


def test_theme_rejects_a_name_that_is_not_a_string() -> None:
    with pytest.raises(TypeError, match="theme name must be a string"):
        Theme(7, light=LIGHT, dark=DARK)  # ty: ignore[invalid-argument-type]


def test_theme_requires_two_palettes() -> None:
    with pytest.raises(TypeError, match="theme light must be a Palette"):
        Theme("acme", light="#fff", dark=DARK)  # ty: ignore[invalid-argument-type]
    with pytest.raises(TypeError, match="theme dark must be a Palette"):
        Theme("acme", light=LIGHT, dark=None)  # ty: ignore[invalid-argument-type]


def test_theme_reports_every_contrast_requirement() -> None:
    report = Theme.PAPER.report()

    assert len(report) == 56
    assert [check.mode for check in report] == ["light"] * 28 + ["dark"] * 28
    assert all(check.passes for check in report)
    first = report[0]
    assert isinstance(first, ContrastCheck)
    assert (first.foreground, first.background, first.required) == (
        "ink",
        "paper",
        4.5,
    )
    assert first.ratio == pytest.approx(13.9, abs=0.1)
    pairs = {(check.foreground, check.background, check.required) for check in report}
    assert ("muted", "panel_raised", 4.5) in pairs
    assert ("accent_ink", "accent", 4.5) in pairs
    assert ("panel", "danger", 4.5) in pairs
    assert ("warning", "panel", 3.0) in pairs
    # Text in a tone is the tone mixed with the ink.
    assert ("warning text", "paper", 4.5) in pairs
    assert ("accent text", "panel", 4.5) in pairs


def test_theme_with_low_contrast_fails_and_names_each_pair() -> None:
    faint = LIGHT.derive(muted="#b5ada0")

    with pytest.raises(ThemeContrastError) as raised:
        Theme("faint", light=faint, dark=DARK)

    error = raised.value
    assert isinstance(error, ValueError)
    assert error.theme == "faint"
    assert [
        (check.mode, check.foreground, check.background) for check in error.failures
    ] == [
        ("light", "muted", "paper"),
        ("light", "muted", "panel"),
        ("light", "muted", "panel_raised"),
    ]
    message = str(error)
    assert "theme 'faint' does not reach the required contrast" in message
    assert "light muted on paper is 1.89:1 and needs 4.5:1" in message
    assert "allow_low_contrast=True" in message


def test_allow_low_contrast_builds_the_theme_and_keeps_the_report() -> None:
    theme = Theme(
        "faint", light=LIGHT.derive(muted="#b5ada0"), dark=DARK, allow_low_contrast=True
    )

    assert [check.passes for check in theme.report()].count(False) == 3

    with pytest.raises(TypeError, match="allow_low_contrast must be a bool"):
        Theme("faint", light=LIGHT, dark=DARK, allow_low_contrast=1)  # ty: ignore[invalid-argument-type]


def test_theme_css_pairs_each_color_for_the_light_and_the_dark_mode() -> None:
    css = Theme("acme", light=LIGHT, dark=DARK).css()
    lines = css.splitlines()

    assert lines[0] == '[data-tori-ui-theme="acme"] {'
    assert lines[1] == "  --tori-ui-paper: light-dark(#f2ecdf, #191816);"
    assert "  --tori-ui-shadow-color: light-dark(#2d241829, #0000006b);" in lines
    # The composed shadow follows the theme's own shadow color.
    assert lines[-2].startswith("  --tori-ui-shadow: var(--tori-ui-shadow-x) ")
    assert lines[-2].endswith("var(--tori-ui-shadow-color);")
    assert lines[-1] == "}"
    assert len(lines) == 15 + 3


# -------------------------------------------------------------------- Skin


def test_bundled_skins_derive_from_the_editorial_skin() -> None:
    assert [skin.name for skin in (Skin.EDITORIAL, Skin.MINIMAL, Skin.ROUNDED)] == [
        "editorial",
        "minimal",
        "rounded",
    ]
    assert Skin.MINIMAL.border_width == Skin.EDITORIAL.border_width == "1px"
    assert Skin.MINIMAL.radius_pill == "999px"
    assert Skin.ROUNDED.radius_surface == "1rem"
    assert Skin.EDITORIAL.control_text_transform == "uppercase"


def test_skin_derive_takes_a_new_name_and_changes() -> None:
    compact = Skin.MINIMAL.derive(
        "compact",
        radius_control="0.5rem",
        font_body=["Inter", "system-ui", "sans-serif"],
        hover_translate="-2px",
    )

    assert compact.name == "compact"
    assert compact.font_body == ("Inter", "system-ui", "sans-serif")
    tokens = compact.tokens()
    assert tokens["radius-control"] == "0.5rem"
    # Generic families are bare; every other family is quoted.
    assert tokens["font-body"] == '"Inter", system-ui, sans-serif'
    assert tokens["hover-translate"] == "-2px"
    assert tokens["space-md"] == Skin.MINIMAL.space_md
    assert Skin.MINIMAL.radius_control == "0.15rem"


@pytest.mark.parametrize(
    ("token", "value", "message"),
    [
        ("space_md", "1", "skin space_md must be 0 or a length"),
        ("space_md", "1 rem", "skin space_md must be 0 or a length"),
        ("space_md", "-1rem", "skin space_md must be 0 or a length"),
        ("space_md", "calc(1rem + 2px)", "skin space_md must be 0 or a length"),
        ("space_md", "1rem; color: red", "skin space_md must be 0 or a length"),
        ("radius_control", "var(--x)", "skin radius_control must be 0 or a length"),
        ("shadow_x", "4", "skin shadow_x must be 0 or a signed length"),
        (
            "button_padding_sm",
            "1rem 1rem 1rem 1rem 1rem",
            "skin button_padding_sm must be one to four lengths",
        ),
        ("alert_padding", "1rem  1rem", "skin alert_padding must be one to four"),
        ("font_body", (), "skin font_body must name one to twelve font families"),
        ("font_body", ("Inter;",), "skin font_body family names may hold"),
        ("font_body", ('"Inter"',), "skin font_body family names may hold"),
        ("font_body", ("url(x)",), "skin font_body family names may hold"),
        ("control_font_weight", 0, "skin control_font_weight must be from 1 to 1000"),
        ("control_text_transform", "upper", "skin control_text_transform must be one"),
        ("disabled_opacity", 1.5, "skin disabled_opacity must be from 0 to 1"),
    ],
)
def test_skin_rejects_values_outside_the_kind_of_their_token(
    token: str, value: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Skin.EDITORIAL.derive("broken", **{token: value})


@pytest.mark.parametrize(
    ("token", "value", "message"),
    [
        ("space_md", 1, "skin space_md must be a string"),
        ("font_body", "Inter", "skin font_body must be a tuple of font family names"),
        ("font_body", (1,), "skin font_body must be a tuple of font family names"),
        ("control_font_weight", "700", "skin control_font_weight must be an integer"),
        ("control_font_weight", True, "skin control_font_weight must be an integer"),
        ("disabled_opacity", "0.5", "skin disabled_opacity must be a number"),
        ("label_text_transform", None, "skin label_text_transform must be a string"),
    ],
)
def test_skin_rejects_values_of_the_wrong_type(
    token: str, value: object, message: str
) -> None:
    with pytest.raises(TypeError, match=message):
        Skin.EDITORIAL.derive("broken", **{token: value})


def test_offsets_may_be_negative_and_fractions_need_no_leading_zero() -> None:
    skin = Skin.EDITORIAL.derive(
        "shifted",
        shadow_spread="-20px",
        label_letter_spacing="-.01em",
        space_xs=".25rem",
        radius_surface="0",
        disabled_opacity=1,
    )

    assert skin.shadow_spread == "-20px"
    assert skin.tokens()["disabled-opacity"] == "1"


@pytest.mark.parametrize(
    "token",
    [
        "border_width",
        "accent_border_width",
        "shadow_x",
        "shadow_y",
        "shadow_blur",
        "shadow_spread",
        "focus_width",
        "focus_offset",
        "field_focus_offset",
    ],
)
def test_length_only_properties_reject_percentages(token: str) -> None:
    with pytest.raises(ValueError, match="without a percentage"):
        Skin.MINIMAL.derive("invalid", **{token: "10%"})


def test_percentage_sizes_remain_supported_where_css_accepts_them() -> None:
    skin = Skin.MINIMAL.derive("relative", radius_control="50%", space_md="5%")
    assert skin.radius_control == "50%"
    assert skin.space_md == "5%"


def test_skin_derive_rejects_unknown_tokens_and_bad_names() -> None:
    with pytest.raises(TypeError, match="unknown skin tokens: radius"):
        Skin.EDITORIAL.derive("acme", radius="1rem")
    with pytest.raises(ValueError, match="skin name must match"):
        Skin.EDITORIAL.derive("Acme")


def test_every_skin_field_has_a_value_kind() -> None:
    fields = [field.name for field in dataclasses.fields(Skin)]

    assert fields[0] == "name"
    assert fields[1:] == list(theming._SKIN_KINDS)
    assert len(fields) == 50


def test_skin_css_declares_every_token_and_the_composed_ones() -> None:
    lines = Skin.EDITORIAL.css().splitlines()

    assert lines[0] == '[data-tori-ui-skin="editorial"] {'
    assert lines[-1] == "}"
    assert len(lines) == 49 + 2 + 2
    assert (
        '  --tori-ui-font-display: "Iowan Old Style", "Palatino Linotype", '
        '"Book Antiqua", "Georgia", serif;'
    ) in lines
    assert "  --tori-ui-control-font-weight: 750;" in lines
    assert "  --tori-ui-disabled-opacity: 0.46;" in lines
    assert "  --tori-ui-card-header-padding: 1.15rem 1.2rem 0.95rem;" in lines
    # A skin on an inner element composes these from its own parts.
    assert lines[-3] == (
        "  --tori-ui-radius-surface-inner: max(0px, "
        "calc(var(--tori-ui-radius-surface) - var(--tori-ui-border-width)));"
    )
    assert lines[-2].startswith("  --tori-ui-shadow: var(--tori-ui-shadow-x) ")


@pytest.mark.parametrize(
    "css",
    [
        Theme.PAPER.css(),
        Skin.EDITORIAL.css(),
        Skin.MINIMAL.css(),
        Skin.ROUNDED.css(),
    ],
)
def test_generated_css_is_one_rule_of_prefixed_declarations(css: str) -> None:
    lines = css.splitlines()

    assert css.count("{") == css.count("}") == 1
    for line in lines[1:-1]:
        assert line.startswith("  --tori-ui-")
        assert line.endswith(";")
        assert line.count(";") == 1
    for forbidden in ("@", "url(", "/*", "<", "\\"):
        assert forbidden not in css


# ----------------------------------------------------- Bundled definitions


@pytest.mark.parametrize("theme", theming._BUNDLED_THEMES)
def test_bundled_themes_meet_every_contrast_requirement(theme: Theme) -> None:
    assert not theme.allow_low_contrast
    assert all(check.passes for check in theme.report())


def test_bundled_css_makes_the_first_theme_and_skin_the_defaults() -> None:
    css = theming._bundled_css()

    assert css.startswith("/* Tokens generated from the bundled theme and skin")
    # A document without attributes gets the paper theme and editorial skin.
    assert ':root,\n[data-tori-ui-theme="paper"] {\n' in css
    assert ':root,\n[data-tori-ui-skin="editorial"] {\n' in css
    for mode, scheme in (("light", "light"), ("dark", "dark"), ("auto", "light dark")):
        rule = f'[data-tori-ui-mode="{mode}"] {{\n  color-scheme: {scheme};\n}}\n'
        assert rule in css
    # Every other bundled definition is its own complete rule.
    assert Skin.MINIMAL.css() in css
    assert Skin.ROUNDED.css() in css
    assert "prefers-color-scheme" not in css
    assert Theme.SLATE.css() in css
    assert Theme.CONTRAST.css() in css
    assert css.count("{") == css.count("}") == 3 + 3 + 3


# -------------------------------------------------------------- Derivation

_ACCENTS = [
    "#ff0000",
    "#00ff00",
    "#0000ff",
    "#ffff00",
    "#ff00ff",
    "#00ffff",
    "#000000",
    "#ffffff",
    "#808080",
    "#c43f27",
    "#7c3aed",
    "#f59e0b",
]


def _picked(palette: Palette) -> dict[str, str]:
    names = ("paper", "panel", "ink", "muted", "accent", "accent_ink", "danger")
    return {name: getattr(palette, name) for name in names}


def test_bundled_themes_are_paper_and_two_derived_themes() -> None:
    assert theming._BUNDLED_THEMES == (Theme.PAPER, Theme.SLATE, Theme.CONTRAST)
    assert [theme.name for theme in theming._BUNDLED_THEMES] == [
        "paper",
        "slate",
        "contrast",
    ]


def test_slate_is_derived_from_a_blue_accent_and_a_slate_neutral() -> None:
    slate = Theme.from_seeds("slate", accent="#2563eb", neutral="#64748b")

    assert slate == Theme.SLATE
    assert _picked(slate.light) == {
        "paper": "#eef4fc",
        "panel": "#fcfdff",
        "ink": "#121b28",
        "muted": "#5e6a7b",
        "accent": "#2563eb",
        "accent_ink": "#fafcff",
        "danger": "#cb473f",
    }
    assert _picked(slate.dark) == {
        "paper": "#101620",
        "panel": "#1a212b",
        "ink": "#dfecff",
        "muted": "#9facbe",
        "accent": "#73a2ff",
        "accent_ink": "#09121f",
        "danger": "#f27d72",
    }
    assert slate.light.shadow_color == "#09121f29"
    assert slate.dark.scrim == "#030a169e"


def test_contrast_is_derived_at_the_high_level_without_a_tint() -> None:
    contrast = Theme.from_seeds("contrast", accent="#0050d8", contrast="high")

    assert contrast == Theme.CONTRAST
    assert _picked(contrast.light) == {
        "paper": "#ffffff",
        "panel": "#ffffff",
        "ink": "#000000",
        "muted": "#484848",
        "accent": "#004bcd",
        "accent_ink": "#ffffff",
        "danger": "#a92321",
    }
    assert _picked(contrast.dark) == {
        "paper": "#000000",
        "panel": "#090909",
        "ink": "#ffffff",
        "muted": "#cacaca",
        "accent": "#9abeff",
        "accent_ink": "#000000",
        "danger": "#ffa096",
    }


def test_from_seeds_keeps_an_accent_that_already_works() -> None:
    violet = Theme.from_seeds("violet", accent="#7c3aed")

    # The seed is readable on the light surfaces, so it is used as it is.
    assert violet.light.accent == "#7c3aed"
    assert violet.light.accent_ink == "#fcfbff"
    # The dark palette lifts it and labels it with a dark ink.
    assert violet.dark.accent == "#aa8eff"
    assert violet.dark.accent_ink == "#121117"


@pytest.mark.parametrize("accent", _ACCENTS)
@pytest.mark.parametrize("neutral", [None, "#64748b", "#78716c", "#ff0000"])
def test_from_seeds_reaches_aa_for_any_seed(accent: str, neutral: str | None) -> None:
    theme = Theme.from_seeds("seeded", accent=accent, neutral=neutral)

    assert all(check.passes for check in theme.report())


@pytest.mark.parametrize("accent", _ACCENTS)
def test_from_seeds_reaches_aaa_for_text_at_the_high_level(accent: str) -> None:
    theme = Theme.from_seeds("seeded", accent=accent, contrast="high")

    for check in theme.report():
        assert check.passes
        if check.required == 4.5:
            assert check.ratio >= 7.0, check
        else:
            assert check.ratio >= 4.5, check


def test_the_neutral_seed_tints_the_surfaces_and_the_text() -> None:
    cool = Theme.from_seeds("cool", accent="#2563eb", neutral="#64748b")
    warm = Theme.from_seeds("warm", accent="#2563eb", neutral="#78716c")
    plain = Theme.from_seeds("plain", accent="#2563eb")

    assert cool.light.accent == warm.light.accent == plain.light.accent
    assert len({cool.light.paper, warm.light.paper, plain.light.paper}) == 3
    assert len({cool.dark.ink, warm.dark.ink, plain.dark.ink}) == 3


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        ({"accent": "blue"}, ValueError, "theme accent must be a #rgb"),
        ({"accent": "#2563eb80"}, ValueError, "theme accent must be an opaque color"),
        ({"accent": 0x2563EB}, TypeError, "theme accent must be a string"),
        (
            {"accent": "#2563eb", "neutral": "gray"},
            ValueError,
            "theme neutral must be a #rgb",
        ),
        (
            {"accent": "#2563eb", "contrast": "maximum"},
            ValueError,
            "theme contrast must be one of: standard, high",
        ),
    ],
)
def test_from_seeds_rejects_invalid_seeds(
    arguments: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        Theme.from_seeds("seeded", **arguments)  # ty: ignore[invalid-argument-type]


def test_from_seeds_validates_the_name_like_any_theme() -> None:
    with pytest.raises(ValueError, match="theme name must match"):
        Theme.from_seeds("Seeded", accent="#2563eb")


# ------------------------------------------------------------ Scoped looks


def test_themed_wraps_content_in_a_surface_with_the_given_look() -> None:
    result = html(
        themed(t"<p>Preview</p>", theme=Theme.SLATE, mode="dark", skin=Skin.ROUNDED)
    ).to_html()

    assert result == (
        '<div class="tori-ui-themed" data-tori-ui-theme="slate" '
        'data-tori-ui-mode="dark" data-tori-ui-skin="rounded"><p>Preview</p></div>'
    )


def test_themed_leaves_out_what_the_document_decides() -> None:
    dark = html(themed("x", mode="dark", id="night")).to_html()
    brand = html(themed("x", theme="brand-2026", skin="acme")).to_html()

    assert (
        dark
        == '<div id="night" class="tori-ui-themed" data-tori-ui-mode="dark">x</div>'
    )
    assert brand == (
        '<div class="tori-ui-themed" data-tori-ui-theme="brand-2026" '
        'data-tori-ui-skin="acme">x</div>'
    )


def test_themed_escapes_its_content() -> None:
    assert "&lt;script&gt;" in html(themed("<script>", mode="light")).to_html()


@pytest.mark.parametrize(
    ("arguments", "error", "message"),
    [
        ({}, ValueError, "themed needs a theme, a mode, or a skin"),
        (
            {"mode": "night"},
            ValueError,
            "themed mode must be one of: auto, dark, light",
        ),
        ({"theme": Skin.ROUNDED}, TypeError, "theme must be a Theme or a string"),
        ({"skin": Theme.PAPER}, TypeError, "skin must be a Skin or a string"),
        ({"theme": 'x" onclick="y'}, ValueError, "theme must match"),
        ({"skin": "Rounded"}, ValueError, "skin must match"),
        ({"mode": "dark", "id": "two words"}, ValueError, "themed id cannot contain"),
    ],
)
def test_themed_rejects_invalid_looks(
    arguments: dict[str, object], error: type[Exception], message: str
) -> None:
    with pytest.raises(error, match=message):
        themed("x", **arguments)  # ty: ignore[invalid-argument-type]
