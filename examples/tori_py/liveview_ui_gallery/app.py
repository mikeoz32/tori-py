"""A gallery of every `tori-py-liveview-ui` component."""

from tori_py import HttpResponse, NestApplication, controller, get, module
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_liveview import LiveViewModule, LiveViewOptions
from tori_py_liveview_ui import LiveViewUiModule

from examples.tori_py.liveview_ui_gallery.actions import ActionsLive
from examples.tori_py.liveview_ui_gallery.ai import AiLive
from examples.tori_py.liveview_ui_gallery.chat import ChatLive
from examples.tori_py.liveview_ui_gallery.content import SAMPLE_IMAGE, ContentLive
from examples.tori_py.liveview_ui_gallery.disclosure import DisclosureLive
from examples.tori_py.liveview_ui_gallery.display import DisplayLive
from examples.tori_py.liveview_ui_gallery.feedback import FeedbackLive
from examples.tori_py.liveview_ui_gallery.forms import FormsLive
from examples.tori_py.liveview_ui_gallery.layout import LayoutLive
from examples.tori_py.liveview_ui_gallery.overview import OverviewLive

_SAMPLE_IMAGE = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">'
    b'<rect width="320" height="180" fill="#f2ecdf"/>'
    b'<circle cx="120" cy="90" r="56" fill="#c43f27" fill-opacity="0.85"/>'
    b'<circle cx="170" cy="90" r="56" fill="#176b87" fill-opacity="0.75"/>'
    b'<circle cx="220" cy="90" r="56" fill="#2f7450" fill-opacity="0.65"/></svg>'
)


@controller()
class SampleController:
    @get(SAMPLE_IMAGE)
    async def sample_image(self) -> HttpResponse:
        return HttpResponse(_SAMPLE_IMAGE, headers={"content-type": "image/svg+xml"})


liveview_module = LiveViewModule.for_root(
    LiveViewOptions(secret="development-secret-change-me-0000"),
    pages=[
        OverviewLive,
        ActionsLive,
        LayoutLive,
        ContentLive,
        DisplayLive,
        FeedbackLive,
        DisclosureLive,
        FormsLive,
        AiLive,
        ChatLive,
    ],
)


@module(
    imports=[liveview_module, LiveViewUiModule.for_root()],
    controllers=[SampleController],
)
class AppModule:
    pass


async def create_application() -> NestApplication:
    return await NestApplication.create(AppModule, adapter=StarletteAdapter())


application = asgi(create_application)
