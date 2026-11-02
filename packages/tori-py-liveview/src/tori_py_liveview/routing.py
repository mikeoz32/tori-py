from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from starlette.routing import Match, Route

from tori_py_liveview.errors import LiveViewConfigurationError, LiveViewError
from tori_py_liveview.options import normalize_origin

_C0_CONTROL_OR_SPACE = "".join(chr(code) for code in range(0x21))
_TAB_OR_NEWLINE = str.maketrans("", "", "\t\n\r")
_REDIRECT_SCHEMES = frozenset({"", "http", "https"})


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


def clean_url(url: str) -> str:
    """Strip what browsers ignore in a URL and read ``\\`` as ``/`` like they do."""
    return url.strip(_C0_CONTROL_OR_SPACE).translate(_TAB_OR_NEWLINE).replace("\\", "/")


def redirect_target(url: str) -> str:
    """Clean a full-reload target and reject anything but a path or http(s) URL."""
    cleaned = clean_url(url)
    try:
        split = urlsplit(cleaned)
    except ValueError:
        split = None
    if (
        split is None
        or not cleaned
        or split.scheme not in _REDIRECT_SCHEMES
        # "https:host" and "//" have no host urlsplit can see.
        or ((split.scheme or cleaned.startswith("//")) and not split.hostname)
    ):
        raise LiveViewError("redirect target must be a path or an http(s) URL")
    return cleaned


def redirect_host_allowed(host: str, url: str, allowed_hosts: tuple[str, ...]) -> bool:
    """Check that a cleaned redirect target stays on the request host name."""
    hostname = urlsplit(url).hostname
    if hostname is None or hostname in allowed_hosts:
        return True
    try:
        return hostname == urlsplit(f"//{host}").hostname
    except ValueError:
        return False


def same_origin(host: str, url: str, *, scheme: str | None = None) -> bool:
    """Check a client URL against the connection host (defense in depth)."""
    try:
        split = urlsplit(clean_url(url))
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
    "clean_url",
    "compile_live_routes",
    "match_live_url",
    "redirect_host_allowed",
    "redirect_target",
    "same_origin",
]
