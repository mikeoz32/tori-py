from __future__ import annotations

import math
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from tori_py_liveview.errors import LiveViewConfigurationError


def websocket_path(socket_path: str) -> str:
    return f"{socket_path}/websocket"


def normalize_origin(value: str) -> str:
    if not isinstance(value, str):
        raise LiveViewConfigurationError("allowed origins must be absolute origins")
    try:
        parsed = urlsplit(value)
        port = (
            parsed.port
            if parsed.port is not None
            else (443 if parsed.scheme == "https" else 80)
        )
    except (AttributeError, ValueError) as error:
        raise LiveViewConfigurationError(
            "allowed origins must be absolute origins"
        ) from error
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise LiveViewConfigurationError("allowed origins must be absolute origins")
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    return f"{parsed.scheme.lower()}://{host}:{port}"


@dataclass(frozen=True, slots=True)
class LiveViewOptions:
    secret: str = field(repr=False)
    socket_path: str = "/_tori/live"
    client_path: str = "/_tori/live.js"
    allowed_origins: tuple[str, ...] = ()
    max_message_bytes: int = 65_536
    token_max_age_ms: int = 86_400_000
    join_timeout_seconds: float = 10.0
    idle_timeout_seconds: float = 75.0

    def __post_init__(self) -> None:
        if not isinstance(self.secret, str) or len(self.secret.encode()) < 32:
            raise LiveViewConfigurationError("secret must contain at least 32 bytes")
        for path in (self.socket_path, self.client_path):
            if (
                not isinstance(path, str)
                or not path.startswith("/")
                or path.startswith("//")
                or path == "/"
                or path.endswith("/")
                or urlsplit(path).path != path
            ):
                raise LiveViewConfigurationError("paths must be absolute")
        if self.socket_path == self.client_path:
            raise LiveViewConfigurationError("socket and client paths must differ")
        if type(self.max_message_bytes) is not int or self.max_message_bytes <= 0:
            raise LiveViewConfigurationError("message size must be positive")
        if type(self.token_max_age_ms) is not int or self.token_max_age_ms <= 0:
            raise LiveViewConfigurationError("token age must be positive")
        if (
            isinstance(self.join_timeout_seconds, bool)
            or not isinstance(self.join_timeout_seconds, int | float)
            or not math.isfinite(self.join_timeout_seconds)
            or self.join_timeout_seconds <= 0
        ):
            raise LiveViewConfigurationError("join timeout must be positive")
        if (
            isinstance(self.idle_timeout_seconds, bool)
            or not isinstance(self.idle_timeout_seconds, int | float)
            or not math.isfinite(self.idle_timeout_seconds)
            or self.idle_timeout_seconds <= 0
        ):
            raise LiveViewConfigurationError("idle timeout must be positive")
        if not isinstance(self.allowed_origins, tuple):
            raise LiveViewConfigurationError("allowed origins must be a tuple")
        object.__setattr__(
            self,
            "allowed_origins",
            tuple(normalize_origin(origin) for origin in self.allowed_origins),
        )


__all__ = ["LiveViewOptions"]
