import asyncio

from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    Rendered,
    UnknownEventError,
    live_view,
    rendered,
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

    def render(self) -> Rendered:
        return rendered(
            (
                '<section id="component-',
                '" data-opal-target="',
                '"><h2>',
                '</h2><button data-opal-click="increment">Increment ',
                '</button><output data-component-id="',
                '">',
                "</output></section>",
            ),
            self.id,
            self.myself,
            self.label,
            self.label,
            self.id,
            self.count,
        )


@live_view("/")
class CounterLive(LiveView):
    def __init__(self) -> None:
        self.count = 0
        self.next_activity = 3
        self.tasks: set[asyncio.Task[None]] = set()

    async def mount(self, context: MountContext) -> None:
        self.count = int(context.query_params.get("start", "0"))
        self.stream_reset("activity-stream")
        self.stream_insert("activity-stream", "activity-1", self._activity_item(1))
        self.stream_insert("activity-stream", "activity-2", self._activity_item(2))

    async def handle_event(self, event: str, value: object) -> None:
        if event == "increment":
            self.count += 1
        elif event == "increment_later":
            task = asyncio.create_task(self._increment_later())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)
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

    async def handle_info(self, name: str, value: object) -> None:
        if name != "increment":
            await super().handle_info(name, value)
            return
        self.count += 1

    async def disconnect(self) -> None:
        tasks = list(self.tasks)
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def render(self) -> Rendered:
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
        return rendered(
            (
                '<main><h1>ToriPy LiveView</h1><button data-opal-click="increment">'
                'Increment page</button><button data-opal-click="increment_later">'
                "Increment later</button><output data-page-counter>",
                '</output><div class="components">',
                "",
                "</div><section><h2>Activity stream</h2><button "
                'data-opal-click="prepend_activity">Prepend activity</button>'
                '<ul id="activity-stream" data-opal-stream>',
                "</ul></section></main>",
            ),
            self.count,
            left,
            right,
            activities,
        )

    def title(self) -> str:
        return f"Counter: {self.count}"

    async def _increment_later(self) -> None:
        await asyncio.sleep(0.1)
        _ = self.send_info("increment")

    @staticmethod
    def _activity_item(sequence: int) -> Rendered:
        item_id = f"activity-{sequence}"
        return rendered(
            (
                '<li id="',
                '"><span>Activity ',
                '</span><button data-opal-click="delete_activity" data-opal-value-id="',
                '">Remove Activity ',
                "</button></li>",
            ),
            item_id,
            sequence,
            item_id,
            sequence,
        )


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="development-secret-change-me-0000"),
    pages=[CounterLive],
)


@module(imports=[liveview_module])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
