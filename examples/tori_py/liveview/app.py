import asyncio
from string.templatelib import Template

from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import (
    LiveComponent,
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    UnknownEventError,
    live_view,
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
        return t"""
            <section id="component-{self.id}" data-opal-target="{self.myself}">
                <h2>{self.label}</h2>
                <button data-opal-click="increment">Increment {self.label}</button>
                <output data-component-id="{self.id}">{self.count}</output>
            </section>
        """


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
        return t"""
            <main>
                <h1>ToriPy LiveView</h1>
                <button data-opal-click="increment">Increment page</button>
                <button data-opal-click="increment_later">Increment later</button>
                <output data-page-counter>{self.count}</output>
                <div class="components">{left}{right}</div>
                <section>
                    <h2>Activity stream</h2>
                    <button data-opal-click="prepend_activity">Prepend activity</button>
                    <ul id="activity-stream" data-opal-stream>{activities}</ul>
                </section>
            </main>
        """

    def title(self) -> str:
        return f"Counter: {self.count}"

    async def _increment_later(self) -> None:
        await asyncio.sleep(0.1)
        _ = self.send_info("increment")

    @staticmethod
    def _activity_item(sequence: int) -> Template:
        item_id = f"activity-{sequence}"
        return t"""
            <li id="{item_id}">
                <span>Activity {sequence}</span>
                <button
                    data-opal-click="delete_activity"
                    data-opal-value-id="{item_id}"
                >
                    Remove Activity {sequence}
                </button>
            </li>
        """


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
