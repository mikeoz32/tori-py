from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from starlette.routing import Match, Route

from tori_py_liveview.errors import LiveViewConfigurationError
from tori_py_liveview.options import normalize_origin


@dataclass(frozen=True, slots=True)
class LiveRoute:
    path: str
    action: str | None
    page: str
    session: str = ""


@dataclass(frozen=True, slots=True)
class CompiledLiveRoute:
    route: LiveRoute
    pattern: Route


def compile_live_routes(
    routes: tuple[LiveRoute, ...],
) -> tuple[CompiledLiveRoute, ...]:
    """Precompile Starlette patterns once per registry."""
    return tuple(
        CompiledLiveRoute(route, Route(route.path, endpoint=_endpoint))
        for route in routes
    )


def match_live_url(
    routes: tuple[CompiledLiveRoute, ...], url: str
) -> tuple[LiveRoute, dict[str, str], str] | None:
    """Resolve a client URL against registered live routes.

    Accepts absolute http(s) URLs and absolute paths. Returns the matched
    route, merged string path/query params, and the original URL. Matching
    reuses Starlette's own route compiler so the live resolver accepts exactly
    the patterns the HTTP controllers serve.
    """
    try:
        split = urlsplit(url)
    except ValueError:
        return None
    if split.scheme in {"http", "https"}:
        if not split.path.startswith("/"):
            return None
    elif split.scheme or split.netloc or not split.path.startswith("/"):
        return None
    for compiled in routes:
        match, child = compiled.pattern.matches(
            {
                "type": "http",
                "method": "GET",
                "path": split.path,
                "headers": [],
                "query_string": split.query.encode("utf-8"),
            }
        )
        if match != Match.FULL:
            continue
        params = dict(parse_qsl(split.query, keep_blank_values=True))
        params.update(
            {name: str(value) for name, value in child.get("path_params", {}).items()}
        )
        return compiled.route, params, url
    return None


def same_origin(host: str, url: str, *, scheme: str | None = None) -> bool:
    """Check a client URL against the connection host (defense in depth)."""
    try:
        split = urlsplit(url)
    except ValueError:
        return False
    if not split.scheme:
        return not split.netloc
    if split.scheme not in {"http", "https"}:
        return False
    if not split.netloc:
        return False
    if scheme is not None:
        try:
            return normalize_origin(f"{scheme}://{host}") == normalize_origin(
                f"{split.scheme}://{split.netloc}"
            )
        except LiveViewConfigurationError, ValueError:
            return False
    return split.netloc.casefold() == host.casefold()


async def _endpoint(request: object) -> object:
    del request
    raise AssertionError("live route resolver never dispatches")


__all__ = [
    "CompiledLiveRoute",
    "LiveRoute",
    "compile_live_routes",
    "match_live_url",
    "same_origin",
]
