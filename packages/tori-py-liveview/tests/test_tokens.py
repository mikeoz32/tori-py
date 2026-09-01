from __future__ import annotations

import pytest
from tori_py_liveview import LiveViewConfigurationError, LiveViewOptions, live_view
from tori_py_liveview.tokens import InvalidMountTokenError, MountTokenCodec


def test_mount_tokens_round_trip_urlsafe_route_state() -> None:
    codec = MountTokenCodec("s" * 32, max_age_ms=60_000)
    token = codec.sign(
        "tests.CounterLive",
        {"member_id": "Mika/42?"},
        "/members/Mika%2F42?filter=%3Cactive%3E",
        now_ms=1_000_000,
    )

    assert token.count(".") == 1
    assert set(token) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_."
    )
    assert codec.verify(token, now_ms=1_030_000) == (
        "tests.CounterLive",
        {"member_id": "Mika/42?"},
        "/members/Mika%2F42?filter=%3Cactive%3E",
    )


def test_mount_tokens_reject_tampering_expiry_and_future_issuance() -> None:
    codec = MountTokenCodec("s" * 32, max_age_ms=1_000)
    token = codec.sign("Counter", {}, "/counter", now_ms=10_000)
    payload, signature = token.split(".")

    with pytest.raises(InvalidMountTokenError):
        codec.verify(f"{payload}A.{signature}", now_ms=10_000)
    with pytest.raises(InvalidMountTokenError):
        codec.verify(token, now_ms=11_001)
    with pytest.raises(InvalidMountTokenError):
        codec.verify(token, now_ms=-20_001)


def test_options_validate_security_and_endpoint_limits() -> None:
    with pytest.raises(LiveViewConfigurationError, match="32 bytes"):
        LiveViewOptions(secret="short")
    with pytest.raises(LiveViewConfigurationError, match="must differ"):
        LiveViewOptions(
            secret="s" * 32,
            socket_path="/_live",
            client_path="/_live",
        )
    with pytest.raises(LiveViewConfigurationError, match="message size"):
        LiveViewOptions(secret="s" * 32, max_message_bytes=0)
    with pytest.raises(LiveViewConfigurationError, match="token age"):
        LiveViewOptions(secret="s" * 32, token_max_age_ms=0)
    with pytest.raises(LiveViewConfigurationError, match="join timeout"):
        LiveViewOptions(secret="s" * 32, join_timeout_seconds=0)
    with pytest.raises(LiveViewConfigurationError, match="idle timeout"):
        LiveViewOptions(secret="s" * 32, idle_timeout_seconds=0)
    for deadline in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(LiveViewConfigurationError, match="join timeout"):
            LiveViewOptions(secret="s" * 32, join_timeout_seconds=deadline)
        with pytest.raises(LiveViewConfigurationError, match="idle timeout"):
            LiveViewOptions(secret="s" * 32, idle_timeout_seconds=deadline)
    with pytest.raises(LiveViewConfigurationError, match="absolute origins"):
        LiveViewOptions(
            secret="s" * 32,
            allowed_origins=("https://user@example.com/path?query=1",),
        )
    with pytest.raises(LiveViewConfigurationError, match="absolute origins"):
        LiveViewOptions(
            secret="s" * 32,
            allowed_origins=("https://example.com:not-a-port",),
        )
    with pytest.raises(LiveViewConfigurationError, match="paths must be absolute"):
        LiveViewOptions(secret="s" * 32, client_path="//cdn.example/client.js")
    with pytest.raises(LiveViewConfigurationError, match="paths must be absolute"):
        LiveViewOptions(secret="s" * 32, socket_path="/_tori/live?admin=true")
    with pytest.raises(LiveViewConfigurationError, match="path must be absolute"):
        live_view("/counter#fragment")

    options = LiveViewOptions(
        secret="s" * 32,
        allowed_origins=("http://example.com:0",),
    )
    assert options.allowed_origins == ("http://example.com:0",)
    assert "s" * 32 not in repr(options)

    options = LiveViewOptions(
        secret="s" * 32,
        allowed_origins=("HTTPS://Example.COM",),
    )
    assert options.allowed_origins == ("https://example.com:443",)
