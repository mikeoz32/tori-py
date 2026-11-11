from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TypeIs, cast


class InvalidMountTokenError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MountToken:
    page: str
    action: str | None
    session: str
    params: dict[str, str]
    resource: str
    flash: dict[str, str] = field(default_factory=dict)


_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_FLASH_PURPOSE = b"flash."
_FLASH_MAX_AGE_MS = 60_000
_RELOAD_PURPOSE = b"reload."
_RELOAD_MAX_AGE_MS = 60_000
_CLOCK_SKEW_MS = 30_000


def _secret(secret: str) -> bytes:
    if len(secret.encode()) < 32:
        raise ValueError("secret must contain at least 32 bytes")
    return secret.encode()


def _max_age(value: int) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("max_age_ms must be a positive integer")
    return value


def _clock() -> int:
    return time.time_ns() // 1_000_000


def _sign(secret: bytes, purpose: bytes, payload: Mapping[str, object]) -> str:
    data = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    encoded = base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    signature = hmac.new(secret, purpose + encoded.encode(), hashlib.sha256)
    return f"{encoded}.{signature.hexdigest()}"


def _verified_object(secret: bytes, purpose: bytes, token: object) -> dict[str, object]:
    """Return the signed JSON object, or raise ``ValueError`` when invalid."""
    if not isinstance(token, str):
        raise ValueError("invalid token")
    try:
        encoded, signature = token.split(".")
    except ValueError as error:
        raise ValueError("invalid token") from error
    if not _B64.fullmatch(encoded) or not _HEX.fullmatch(signature):
        raise ValueError("invalid token")
    expected = hmac.new(secret, purpose + encoded.encode(), hashlib.sha256)
    if not hmac.compare_digest(signature, expected.hexdigest()):
        raise ValueError("invalid token")
    try:
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except ValueError as error:
        raise ValueError("invalid token") from error
    if not isinstance(data, dict):
        raise ValueError("invalid token")
    return cast(dict[str, object], data)


def _fresh(issued: object, now: int, max_age_ms: int) -> bool:
    return (
        type(issued) is int
        and issued <= now + _CLOCK_SKEW_MS
        and now - issued <= max_age_ms
    )


def _string_map(value: object) -> TypeIs[dict[str, str]]:
    return isinstance(value, dict) and all(
        isinstance(key, str) and isinstance(item, str)
        for key, item in cast(dict[object, object], value).items()
    )


class MountTokenCodec:
    def __init__(self, secret: str, *, max_age_ms: int = 300_000) -> None:
        self._secret = _secret(secret)
        self._max_age_ms = _max_age(max_age_ms)

    def sign(
        self,
        page: str,
        params: dict[str, str],
        resource: str,
        action: str | None = None,
        session: str = "",
        *,
        flash: Mapping[str, str] | None = None,
        now_ms: int | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "p": page,
            "g": action,
            "s": session,
            "a": params,
            "r": resource,
            "i": _clock() if now_ms is None else now_ms,
        }
        if flash:
            payload["f"] = dict(flash)
        return _sign(self._secret, b"", payload)

    def verify(self, token: str, *, now_ms: int | None = None) -> MountToken:
        try:
            data = _verified_object(self._secret, b"", token)
            page, params, resource, issued = data["p"], data["a"], data["r"], data["i"]
        except (ValueError, KeyError) as error:
            raise InvalidMountTokenError("invalid mount token") from error
        action = data.get("g")
        session = data.get("s", "")
        flash = data.get("f", {})
        now = _clock() if now_ms is None else now_ms
        if (
            not isinstance(page, str)
            or (action is not None and not isinstance(action, str))
            or not isinstance(session, str)
            or not isinstance(resource, str)
            or not _string_map(params)
            or not _string_map(flash)
            or not _fresh(issued, now, self._max_age_ms)
        ):
            raise InvalidMountTokenError("expired or invalid mount token")
        return MountToken(page, action, session, params, resource, flash)


class FlashTokenCodec:
    """Sign flash carried across a navigation, with Phoenix's 60 second limit.

    Flash tokens use a distinct HMAC purpose, so mount and flash tokens never
    verify as each other.
    """

    def __init__(self, secret: str, *, max_age_ms: int = _FLASH_MAX_AGE_MS) -> None:
        self._secret = _secret(secret)
        self._max_age_ms = _max_age(max_age_ms)

    def sign(self, flash: Mapping[str, str], *, now_ms: int | None = None) -> str:
        payload = {"f": dict(flash), "i": _clock() if now_ms is None else now_ms}
        return _sign(self._secret, _FLASH_PURPOSE, payload)

    def verify(self, token: object, *, now_ms: int | None = None) -> dict[str, str]:
        """Return the signed flash; an invalid or expired token carries none."""
        try:
            data = _verified_object(self._secret, _FLASH_PURPOSE, token)
        except ValueError:
            return {}
        flash = data.get("f")
        now = _clock() if now_ms is None else now_ms
        if not _string_map(flash) or not _fresh(data.get("i"), now, self._max_age_ms):
            return {}
        return dict(flash)


class ReloadTokenCodec:
    """Sign the client error of a connected mount for the official reload cookie.

    The token binds the status to one page identity and resource, uses its own
    HMAC purpose, and expires with the client's 60 second cookie.
    """

    def __init__(self, secret: str, *, max_age_ms: int = _RELOAD_MAX_AGE_MS) -> None:
        self._secret = _secret(secret)
        self._max_age_ms = _max_age(max_age_ms)

    def sign(
        self, page: str, resource: str, status: int, *, now_ms: int | None = None
    ) -> str:
        payload = {
            "p": page,
            "r": resource,
            "s": status,
            "i": _clock() if now_ms is None else now_ms,
        }
        return _sign(self._secret, _RELOAD_PURPOSE, payload)

    def verify(
        self,
        token: object,
        page: str,
        resource: str,
        *,
        now_ms: int | None = None,
    ) -> int | None:
        """Return the client error status signed for this page and resource."""
        try:
            data = _verified_object(self._secret, _RELOAD_PURPOSE, token)
        except ValueError:
            return None
        status = data.get("s")
        now = _clock() if now_ms is None else now_ms
        if (
            data.get("p") != page
            or data.get("r") != resource
            or type(status) is not int
            or not 400 <= status < 500
            or not _fresh(data.get("i"), now, self._max_age_ms)
        ):
            return None
        return status


__all__ = [
    "FlashTokenCodec",
    "InvalidMountTokenError",
    "MountToken",
    "MountTokenCodec",
    "ReloadTokenCodec",
]
