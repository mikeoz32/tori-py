"""A gallery of every `tori-py-liveview-ui` component."""

from tori_py import NestApplication, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import LiveViewModule, LiveViewOptions
from tori_py_liveview_ui import LiveViewUiModule

from examples.tori_py.liveview_ui_gallery.overview import OverviewLive

liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="development-secret-change-me-0000"),
    pages=[OverviewLive],
)


@module(imports=[liveview_module, LiveViewUiModule.for_root()])
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
