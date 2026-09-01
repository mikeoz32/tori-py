from string.templatelib import Template

from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import (
    LiveComponent,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
)
from tori_py_liveview_ui import (
    LiveViewUiModule,
    UiLiveView,
    alert,
    badge,
    button,
    card,
    grid,
    stack,
)


class CounterComponent(LiveComponent):
    def __init__(self) -> None:
        self.count = 0
        self.label = ""

    def update(self, assigns: object) -> None:
        if not isinstance(assigns, dict) or not isinstance(
            label := assigns.get("label"),
            str,
        ):
            raise TypeError("CounterComponent requires a string label")
        self.label = label

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

    def render(self) -> Template:
        action = button(
            f"Increment {self.label}",
            event="increment",
            target=self.myself,
            variant="secondary",
        )
        count = badge(self.count, tone="info")
        return (
            t'<section id="component-{self.id}"><h2>{self.label}</h2>'
            t'{action}<output data-component-id="{self.id}">{self.count}</output>'
            t"{count}</section>"
        )


@live_view("/")
class CounterLive(UiLiveView):
    def __init__(self) -> None:
        self.count = 0
        self.next_activity = 3
        self.show_title = True

    async def mount(self, context: MountContext) -> None:
        self.count = int(context.query_params.get("start", "0"))
        self.stream_reset("activity-stream")
        self.stream_insert("activity-stream", "activity-1", self._activity_item(1))
        self.stream_insert("activity-stream", "activity-2", self._activity_item(2))

    async def handle_event(self, event: str, value: object) -> None:
        if event == "increment":
            self.count += 1
        elif event == "clear_title":
            self.show_title = False
        elif event == "set_count":
            if (
                not isinstance(value, dict)
                or not isinstance(counter := value.get("counter"), dict)
                or not isinstance(raw_count := counter.get("value"), str)
            ):
                raise UnknownEventError(event)
            self.count = int(raw_count)
        elif event == "prepend_activity":
            sequence = self.next_activity
            self.next_activity += 1
            self.stream_insert(
                "activity-stream",
                f"activity-{sequence}",
                self._activity_item(sequence),
                at=0,
                limit=3,
            )
        elif event == "delete_activity":
            if not isinstance(value, dict) or not isinstance(
                item_id := value.get("id"),
                str,
            ):
                raise UnknownEventError(event)
            self.stream_delete("activity-stream", item_id)
        else:
            raise UnknownEventError(event)

    def render(self) -> Template:
        left = self.live_component(
            CounterComponent,
            "left",
            {"label": "Left"},
        )
        right = self.live_component(
            CounterComponent,
            "right",
            {"label": "Right"},
        )
        activities = self.stream_contents("activity-stream")
        form = (
            t'<form id="page-counter-form" phx-change="set_count">'
            t'<label>Set page count <input type="number" '
            t'name="counter[value]" value="{self.count}"></label></form>'
        )
        page_controls = stack(
            [
                form,
                button("Increment page", event="increment"),
                button("Clear title", event="clear_title", variant="ghost"),
                t"<output data-page-counter>{self.count}</output>",
                badge(f"Count {self.count}", tone="success"),
            ],
            gap="sm",
            align="start",
        )
        components = grid([left, right], columns="2", gap="lg")
        prepend_activity = button(
            "Prepend activity",
            event="prepend_activity",
            variant="secondary",
        )
        stream_panel = card(
            t"{prepend_activity}"
            t'<ul id="activity-stream" phx-update="stream">{activities}</ul>',
            eyebrow="Phoenix stream",
            title="Activity stream",
        )
        layout = stack(
            [
                alert(
                    "Official Phoenix LiveView client connected",
                    title="Server-rendered UI",
                    tone="info",
                ),
                card(page_controls, eyebrow="Page state", title="Counter"),
                components,
                stream_panel,
            ],
            gap="lg",
        )
        return t"<main><h1>ToriPy LiveView UI</h1>{layout}</main>"

    def title(self) -> str | None:
        return f"Counter: {self.count}" if self.show_title else None

    @staticmethod
    def _activity_item(sequence: int) -> Template:
        item_id = f"activity-{sequence}"
        return (
            t'<li id="{item_id}"><span>Activity {sequence}</span>'
            t'<button phx-click="delete_activity" phx-value-id="{item_id}">'
            t"Remove Activity {sequence}</button></li>"
        )


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="development-secret-change-me-0000"),
    pages=[CounterLive],
)


@module(imports=[liveview_module, LiveViewUiModule.for_root()])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
