from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import (
    LiveView,
    LiveViewModule,
    LiveViewOptions,
    MountContext,
    Rendered,
    UnknownEventError,
    live_view,
    rendered,
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
        return rendered(
            (
                '<main><h1>ToriPy LiveView</h1><button data-opal-click="increment">'
                "Increment</button><output>",
                "</output></main>",
            ),
            self.count,
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
