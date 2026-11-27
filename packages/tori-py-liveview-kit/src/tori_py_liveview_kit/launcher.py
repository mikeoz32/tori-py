"""Assemble and serve an application with development defaults."""

from __future__ import annotations

import secrets
from collections.abc import Iterable

from tori_py import (
    ModuleImport,
    ModuleProvider,
    NestApplication,
    module,
    provider_token,
)
from tori_py.starlette import ASGIApplication, StarletteAdapter, asgi
from tori_py_liveview import LiveView, LiveViewModule, LiveViewOptions
from tori_py_liveview_ui import LiveViewUiModule


def create_app(
    *pages: type[LiveView],
    secret: str | None = None,
    providers: Iterable[ModuleProvider] = (),
    imports: Iterable[ModuleImport] = (),
) -> ASGIApplication:
    """Return an ASGI application that serves ``pages``.

    Every page keeps its own ``@live_view(path)``. ``providers`` are made
    available to the pages' constructors, and ``imports`` are modules whose
    exports the pages need.

    Without a ``secret`` one is generated for this process: mount tokens end
    with the process, and a browser that reconnects after a restart reloads
    the page. An application that needs authentication, allowed origins, or
    other production settings assembles ``LiveViewModule`` itself.
    """
    declared = tuple(providers)
    needed = list(imports)
    if declared:
        tokens = [
            provider if isinstance(provider, type) else provider_token(provider)
            for provider in declared
        ]

        @module(providers=declared, exports=tokens)
        class KitProvidersModule:
            pass

        needed.append(KitProvidersModule)

    liveview = LiveViewModule.for_root(
        LiveViewOptions(secret=secrets.token_urlsafe(48) if secret is None else secret),
        pages=pages,
        imports=needed,
    )

    @module(imports=[liveview, LiveViewUiModule.for_root()])
    class KitApplicationModule:
        pass

    async def create() -> NestApplication:
        return await NestApplication.create(
            KitApplicationModule, adapter=StarletteAdapter()
        )

    return asgi(create)


def run_app(
    *pages: type[LiveView],
    host: str = "127.0.0.1",
    port: int = 8000,
    secret: str | None = None,
    providers: Iterable[ModuleProvider] = (),
    imports: Iterable[ModuleImport] = (),
) -> None:
    """Serve ``pages`` with uvicorn until the process is interrupted.

    The server listens on the loopback interface unless ``host`` says
    otherwise. It does not reload on a code change; for that, expose
    ``create_app(...)`` as a module attribute and run an ASGI server on it.
    """
    import uvicorn

    application = create_app(
        *pages, secret=secret, providers=providers, imports=imports
    )
    uvicorn.run(application, host=host, port=port, lifespan="on")


__all__ = ["create_app", "run_app"]
