"""Gallery page for themes, modes, and skins."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import live_view
from tori_py_liveview_ui import (
    Skin,
    TableColumn,
    Theme,
    badge,
    button,
    button_group,
    card,
    code_block,
    grid,
    input,
    link_button,
    row,
    stack,
    table,
    text,
    themed,
)

from examples.tori_py.liveview_ui_gallery.looks import (
    COMPACT,
    ORCHID,
    SKINS,
    SOURCE,
    THEMES,
)
from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

# The palette tokens a preview shows as swatches.
_SWATCHES = (
    "paper",
    "panel",
    "ink",
    "muted",
    "line",
    "accent",
    "danger",
    "info",
    "success",
    "warning",
)
_CLOSEST = 8


def _swatch(token: str, color: str) -> Template:
    # The swatch reads the token, so it shows the palette in effect around it.
    style = (
        f"background: var(--tori-ui-{token}); border: 1px solid var(--tori-ui-line); "
        "display: inline-block; inline-size: 1.75rem; block-size: 1.75rem;"
    )
    return t'<span role="img" aria-label="{token} {color}" style="{style}"></span>'


def _preview(theme: Theme, mode: str) -> Template:
    palette = theme.light if mode == "light" else theme.dark
    tokens = palette.tokens()
    body = stack(
        [
            t"<strong>{theme.name}, {mode}</strong>",
            row([_swatch(token, tokens[token]) for token in _SWATCHES], gap="xs"),
            row(
                [
                    button("Primary", size="sm"),
                    button("Secondary", variant="secondary", size="sm"),
                    badge("Info", tone="info"),
                    badge("Danger", tone="danger"),
                ],
                gap="sm",
            ),
            text("Muted text on the paper surface.", size="sm", muted=True),
        ],
        gap="sm",
    )
    padded = t'<div style="padding: var(--tori-ui-space-md);">{body}</div>'
    return themed(
        padded,
        theme=theme,
        mode="light" if mode == "light" else "dark",
        id=f"preview-{theme.name}-{mode}",
    )


def _specimen(skin: Skin) -> Template:
    body = card(
        stack(
            [
                input(
                    "Field",
                    id=f"specimen-{skin.name}",
                    name=f"specimen-{skin.name}",
                    value="A value",
                ),
                row(
                    [button("Save", size="sm"), badge("Draft", tone="warning")],
                    gap="sm",
                ),
            ],
            gap="sm",
        ),
        title=skin.name,
    )
    # The padding is the skin's own spacing, read inside the themed part.
    padded = t'<div style="padding: var(--tori-ui-space-md);">{body}</div>'
    return themed(padded, skin=skin, id=f"skin-{skin.name}")


@live_view("/themes")
class ThemesLive(GalleryPage):
    heading = "Themes"
    summary = "Themes, modes, and skins: the bundled ones and two the gallery defines."
    path = "/themes"

    def ui_extra_definitions(self) -> tuple[Theme | Skin, ...]:
        # The previews show every look, so the document links every stylesheet.
        return (ORCHID, COMPACT)

    def render(self) -> Template:
        themes = button_group(
            (
                link_button(
                    theme.name,
                    href=self.href(self.path, theme=theme),
                    variant="primary" if theme == self.theme else "secondary",
                    size="sm",
                )
                for theme in THEMES.values()
            ),
            label="Theme",
        )
        skins = button_group(
            (
                link_button(
                    skin.name,
                    href=self.href(self.path, skin=skin),
                    variant="primary" if skin == self.skin else "secondary",
                    size="sm",
                )
                for skin in SKINS.values()
            ),
            label="Skin of the page",
        )
        chooser = stack(
            [
                text(
                    "A theme is two palettes. The mode toggle in the header picks "
                    "one of them in the browser; the theme and the skin belong to "
                    "the document, so choosing one loads the page again.",
                    muted=True,
                ),
                row([themes, skins], gap="md"),
                t'<p>Theme <output id="current-theme">{self.theme.name}</output>, '
                t'skin <output id="current-skin">{self.skin.name}</output>.</p>',
            ],
            gap="md",
        )
        previews = grid(
            [
                _preview(theme, mode)
                for theme in THEMES.values()
                for mode in ("light", "dark")
            ],
            columns="2",
        )
        report = self.theme.report()
        closest = sorted(report, key=lambda check: check.ratio / check.required)
        contrast = stack(
            [
                t'<p id="contrast-summary">{sum(check.passes for check in report)} of '
                t"{len(report)} contrast requirements met by {self.theme.name}. "
                t"The closest are:</p>",
                table(
                    [
                        "Mode",
                        "Text or graphic",
                        "Surface",
                        TableColumn("Ratio", align="end"),
                        TableColumn("Needs", align="end"),
                    ],
                    (
                        [
                            check.mode,
                            check.foreground.replace("_", " "),
                            check.background.replace("_", " "),
                            f"{check.ratio:.2f}",
                            f"{check.required:g}",
                        ]
                        for check in closest[:_CLOSEST]
                    ),
                    caption="Contrast",
                    density="compact",
                ),
            ],
            gap="sm",
        )
        specimens = grid([_specimen(skin) for skin in SKINS.values()], columns="2")
        source = stack(
            [
                text(
                    "The orchid theme and the compact skin are defined by the "
                    "gallery and registered with its module.",
                    muted=True,
                ),
                code_block(SOURCE, language="python"),
            ],
            gap="sm",
        )
        return self.page(
            stack(
                [
                    demo("Choose", chooser),
                    demo("Every theme in both modes", previews),
                    demo("Contrast report", contrast),
                    demo("Every skin", specimens),
                    demo("Defined in the application", source),
                ],
                gap="lg",
            )
        )
