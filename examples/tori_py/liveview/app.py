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

    async def mount(self, context: MountContext) -> None:
        self.count = int(context.query_params.get("start", "0"))

    async def handle_event(self, event: str, value: object) -> None:
        del value
        if event != "increment":
            raise UnknownEventError(event)
        self.count += 1

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
        return rendered(
            (
                '<main><h1>ToriPy LiveView</h1><button data-opal-click="increment">'
                "Increment page</button><output data-page-counter>",
                '</output><div class="components">',
                "",
                "</div></main>",
            ),
            self.count,
            left,
            right,
        )

    def title(self) -> str:
        return f"Counter: {self.count}"


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
