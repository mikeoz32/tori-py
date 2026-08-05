"""Validated, secret-redacted RabbitMQ root configuration."""

from __future__ import annotations

import math
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True, repr=False)
class RabbitMqOptions:
    """One immutable AMQP endpoint and bounded connection policy."""

    url: str
    connection_name: str = "nestpy-microservices"
    heartbeat: int = 60
    connection_timeout: float = 10.0
    reconnect_interval: float = 5.0
    tls: bool = False
    rpc_exchange: str = "nestpy.rpc"
    reply_queue_expires_ms: int = 300_000
    retry_delay_ms: int = 1_000
    max_delivery_attempts: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.url, str) or not self.url:
            raise ValueError("url must be a non-empty AMQP URL")
        parsed = urlsplit(self.url)
        if parsed.scheme not in {"amqp", "amqps"} or not parsed.hostname:
            raise ValueError("url must be one amqp:// or amqps:// endpoint")
        try:
            if parsed.port is not None and parsed.port <= 0:
                raise ValueError("url port must be positive")
        except ValueError as error:
            raise ValueError("url has an invalid port") from error
        if parsed.scheme == "amqps" and not self.tls:
            raise ValueError("amqps URLs require tls=True")
        if not isinstance(self.connection_name, str) or not self.connection_name:
            raise ValueError("connection_name must be non-empty")
        if not isinstance(self.heartbeat, int) or isinstance(self.heartbeat, bool):
            raise ValueError("heartbeat must be a positive integer")
        if self.heartbeat <= 0:
            raise ValueError("heartbeat must be a positive integer")
        if not isinstance(self.connection_timeout, (int, float)) or (
            isinstance(self.connection_timeout, bool)
            or not math.isfinite(self.connection_timeout)
            or self.connection_timeout <= 0
        ):
            raise ValueError("connection_timeout must be positive")
        if self.reconnect_interval != 5.0:
            raise ValueError("reconnect_interval is fixed at 5 seconds")
        if not isinstance(self.tls, bool):
            raise ValueError("tls must be boolean")
        if not isinstance(self.rpc_exchange, str) or not self.rpc_exchange:
            raise ValueError("rpc_exchange must be non-empty")
        if not isinstance(self.reply_queue_expires_ms, int) or isinstance(
            self.reply_queue_expires_ms, bool
        ):
            raise ValueError("reply_queue_expires_ms must be a positive integer")
        if self.reply_queue_expires_ms <= 0:
            raise ValueError("reply_queue_expires_ms must be a positive integer")
        for name in ("retry_delay_ms", "max_delivery_attempts"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    def __repr__(self) -> str:
        parsed = urlsplit(self.url)
        host = parsed.hostname or "unknown"
        redacted = f"{parsed.scheme}://{host}"
        return (
            "RabbitMqOptions("
            f"url={redacted!r}, connection_name={self.connection_name!r}, "
            f"heartbeat={self.heartbeat}, "
            f"connection_timeout={self.connection_timeout!r}, "
            f"reconnect_interval={self.reconnect_interval!r}, tls={self.tls!r}, "
            f"rpc_exchange={self.rpc_exchange!r}, "
            f"reply_queue_expires_ms={self.reply_queue_expires_ms}, "
            f"retry_delay_ms={self.retry_delay_ms}, "
            f"max_delivery_attempts={self.max_delivery_attempts})"
        )


__all__ = ["RabbitMqOptions"]
