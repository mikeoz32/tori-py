"""Gallery page for form controls."""

from __future__ import annotations

from string.templatelib import Template

from tori_py_liveview import UnknownEventError, live_view
from tori_py_liveview_ui import (
    button,
    checkbox,
    checkbox_group,
    combobox,
    description_list,
    fieldset,
    form,
    form_actions,
    grid,
    hidden,
    input,
    multi_select,
    radio_group,
    search,
    segmented,
    select,
    slider,
    stack,
    switch,
    textarea,
)

from examples.tori_py.liveview_ui_gallery.shell import GalleryPage, demo

_PLANS = [("free", "Free"), ("team", "Team"), ("business", "Business")]
_TOPICS = [("product", "Product news"), ("tips", "Tips"), ("events", "Events")]
_CITIES = ["Kyiv", "Lviv", "Odesa", "Kharkiv", "Dnipro"]
_ORDERS = ["Analytical engine", "Compiler", "Shortest path", "Sorting network"]


def _text(values: dict[str, object], key: str, default: str = "") -> str:
    value = values.get(key, default)
    return value if isinstance(value, str) else default


def _list(values: dict[str, object], key: str) -> list[str]:
    value = values.get(key)
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


@live_view("/forms")
class FormsLive(GalleryPage):
    heading = "Forms"
    summary = "Every form control, validated by the page as you type."
    path = "/forms"

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, object] = {
            "name": "",
            "seats": "5",
            "plan": "team",
            "topics": ["product"],
            "view": "list",
            "city": "",
            "roles": ["editor"],
            "volume": "40",
            "notify": "true",
        }
        self.saved = 0
        self.query = ""

    async def handle_event(self, event: str, value: object) -> None:
        match event, value:
            case "validate" | "save", {"account": dict(account)}:
                self.values = dict(account)
                if event == "save" and self.name_error() is None:
                    self.saved += 1
            case "find", {"q": str(query)}:
                self.query = query
            case _:
                raise UnknownEventError(event)

    def name_error(self) -> str | None:
        name = _text(self.values, "name")
        return None if len(name.strip()) >= 2 else "Enter at least two characters."

    def render(self) -> Template:
        values = self.values
        name = _text(values, "name")
        volume = _text(values, "volume", "40")
        text_fields = stack(
            [
                input(
                    "Name",
                    id="name",
                    name="account[name]",
                    value=name,
                    error=self.name_error() if name else None,
                    required=True,
                    min_length=2,
                    max_length=40,
                    debounce=200,
                ),
                input(
                    "Seats",
                    id="seats",
                    name="account[seats]",
                    value=_text(values, "seats", "5"),
                    input_type="number",
                    minimum=1,
                    maximum=500,
                    suffix="seats",
                ),
                combobox(
                    "City",
                    _CITIES,
                    id="city",
                    name="account[city]",
                    value=_text(values, "city"),
                    placeholder="Start typing",
                ),
                textarea("Notes", id="notes", name="account[notes]", rows=2),
            ]
        )
        choices = stack(
            [
                radio_group(
                    "Plan",
                    _PLANS,
                    id="plan",
                    name="account[plan]",
                    value=_text(values, "plan"),
                    inline=True,
                ),
                checkbox_group(
                    "Email topics",
                    _TOPICS,
                    id="topics",
                    name="account[topics][]",
                    values=_list(values, "topics"),
                ),
                segmented(
                    "Default view",
                    [("list", "List"), ("board", "Board"), ("calendar", "Calendar")],
                    id="view",
                    name="account[view]",
                    value=_text(values, "view"),
                ),
            ]
        )
        more = stack(
            [
                switch(
                    "Notify me about replies",
                    id="notify",
                    name="account[notify]",
                    checked=values.get("notify") == "true",
                    help_text="You can change this at any time.",
                ),
                checkbox("I accept the terms", id="terms", name="account[terms]"),
                slider(
                    "Volume",
                    id="volume",
                    name="account[volume]",
                    value=int(volume) if volume.isdigit() else 40,
                ),
                multi_select(
                    "Roles",
                    [("viewer", "Viewer"), ("editor", "Editor"), ("admin", "Admin")],
                    id="roles",
                    name="account[roles][]",
                    values=_list(values, "roles"),
                    size=3,
                ),
                select(
                    "Language",
                    [("en", "English"), ("uk", "Ukrainian")],
                    id="language",
                    name="account[language]",
                    value="en",
                ),
            ]
        )
        account = form(
            stack(
                [
                    hidden(name="account[version]", value=3),
                    grid(
                        [
                            fieldset("Profile", text_fields),
                            fieldset("Choices", choices),
                            fieldset(
                                "Preferences", more, description="Stored per account."
                            ),
                        ],
                        columns="3",
                        gap="lg",
                    ),
                    form_actions(
                        [
                            button("Reset", variant="ghost", button_type="reset"),
                            button("Save", button_type="submit", disable_with="Saving"),
                        ]
                    ),
                ],
                gap="lg",
            ),
            id="account-form",
            change_event="validate",
            submit_event="save",
        )
        notify = _text(values, "notify", "off")
        state = description_list(
            [
                ("Name", t'<output id="state-name">{name}</output>'),
                ("Plan", t'<output id="state-plan">{_text(values, "plan")}</output>'),
                (
                    "Topics",
                    t'<output id="state-topics">'
                    t"{', '.join(_list(values, 'topics'))}</output>",
                ),
                ("View", t'<output id="state-view">{_text(values, "view")}</output>'),
                (
                    "Roles",
                    t'<output id="state-roles">'
                    t"{', '.join(_list(values, 'roles'))}</output>",
                ),
                ("Volume", t'<output id="state-volume">{volume}</output>'),
                (
                    "Notify",
                    t'<output id="state-notify">{notify}</output>',
                ),
                ("Saved", t'<output id="state-saved">{self.saved}</output>'),
            ]
        )
        matches = [order for order in _ORDERS if self.query.lower() in order.lower()]
        finder = form(
            stack(
                [
                    search(
                        "Search orders",
                        id="q",
                        name="q",
                        value=self.query,
                        debounce=150,
                    ),
                    t'<output id="matches">{", ".join(matches)}</output>',
                ]
            ),
            id="search-form",
            change_event="find",
        )
        return self.page(
            stack(
                [
                    account,
                    grid(
                        [demo("What the page received", state), demo("Search", finder)],
                        columns="2",
                        gap="lg",
                    ),
                ],
                gap="lg",
            )
        )
