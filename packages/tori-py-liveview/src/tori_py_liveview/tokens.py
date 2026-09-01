from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time


class InvalidMountTokenError(ValueError):
    pass


_B64 = re.compile(r"[A-Za-z0-9_-]+\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")


class MountTokenCodec:
    def __init__(self, secret: str, *, max_age_ms: int = 300_000) -> None:
        if len(secret.encode()) < 32:
            raise ValueError("secret must contain at least 32 bytes")
        if type(max_age_ms) is not int or max_age_ms <= 0:
            raise ValueError("max_age_ms must be a positive integer")
        self._secret = secret.encode()
        self._max_age_ms = max_age_ms

    def sign(
        self,
        page: str,
        params: dict[str, str],
        resource: str,
        *,
        now_ms: int | None = None,
    ) -> str:
        issued = self._clock() if now_ms is None else now_ms
        payload = json.dumps(
            {"p": page, "a": params, "r": resource, "i": issued},
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
        signature = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        return f"{encoded}.{signature}"

    def verify(
        self, token: str, *, now_ms: int | None = None
    ) -> tuple[str, dict[str, str], str]:
        try:
            encoded, signature = token.split(".")
        except (AttributeError, ValueError) as error:
            raise InvalidMountTokenError("invalid mount token") from error
        if not _B64.fullmatch(encoded) or not _HEX.fullmatch(signature):
            raise InvalidMountTokenError("invalid mount token")
        expected = hmac.new(self._secret, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidMountTokenError("invalid mount token")
        try:
            raw = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            data = json.loads(raw)
            page, params, resource, issued = data["p"], data["a"], data["r"], data["i"]
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise InvalidMountTokenError("invalid mount token") from error
        now = self._clock() if now_ms is None else now_ms
        if (
            not isinstance(page, str)
            or not isinstance(resource, str)
            or type(issued) is not int
            or not isinstance(params, dict)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in params.items()
            )
            or issued > now + 30_000
            or now - issued > self._max_age_ms
        ):
            raise InvalidMountTokenError("expired or invalid mount token")
        return page, params, resource

    @staticmethod
    def _clock() -> int:
        return time.time_ns() // 1_000_000


__all__ = ["InvalidMountTokenError", "MountTokenCodec"]
