"""Sanitized diagnostics for framework-owned HTTP failure boundaries."""

import logging
import uuid


def log_http_emergency(logger: logging.Logger, code: str) -> None:
    """Emit a value-free emergency event safe for untrusted request failures."""

    logger.error(code, extra={"event_id": str(uuid.uuid4())})


__all__ = ["log_http_emergency"]
