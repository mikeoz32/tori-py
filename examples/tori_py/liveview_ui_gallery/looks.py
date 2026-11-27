"""The looks the gallery offers: the bundled ones and two of its own."""

from __future__ import annotations

from tori_py_liveview_ui import Skin, Theme

# An application theme: both palettes are derived from two colors.
ORCHID = Theme.from_seeds("orchid", accent="#a21caf", neutral="#6b5876")

# An application skin: a bundled skin with a few tokens changed.
COMPACT = Skin.MINIMAL.derive(
    "compact",
    radius_control="0.5rem",
    radius_surface="0.5rem",
    field_control_radius="0.5rem",
    control_height_md="2.1rem",
    field_control_height="2.3rem",
    font_display=("ui-rounded", "system-ui", "sans-serif"),
)

# What the gallery shows as source on its Themes page.
SOURCE = """\
from tori_py_liveview_ui import LiveViewUiModule, Skin, Theme

ORCHID = Theme.from_seeds("orchid", accent="#a21caf", neutral="#6b5876")
COMPACT = Skin.MINIMAL.derive(
    "compact",
    radius_control="0.5rem",
    radius_surface="0.5rem",
    field_control_radius="0.5rem",
    control_height_md="2.1rem",
    field_control_height="2.3rem",
    font_display=("ui-rounded", "system-ui", "sans-serif"),
)

ui_module = LiveViewUiModule.for_root(themes=[ORCHID], skins=[COMPACT])
"""

THEMES: dict[str, Theme] = {
    theme.name: theme for theme in (Theme.PAPER, Theme.SLATE, Theme.CONTRAST, ORCHID)
}
SKINS: dict[str, Skin] = {
    skin.name: skin for skin in (Skin.EDITORIAL, Skin.MINIMAL, Skin.ROUNDED, COMPACT)
}
