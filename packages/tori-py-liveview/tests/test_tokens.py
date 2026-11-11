from __future__ import annotations

from typing import Any, cast

import pytest
from tori_py_liveview import LiveViewConfigurationError, LiveViewOptions, live_view
from tori_py_liveview.tokens import (
    ChildToken,
    ChildTokenCodec,
    FlashTokenCodec,
    InvalidMountTokenError,
    MountToken,
    MountTokenCodec,
    ReloadTokenCodec,
)


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
    assert codec.verify(token, now_ms=1_030_000) == MountToken(
        "tests.CounterLive",
        None,
        "",
        {"member_id": "Mika/42?"},
        "/members/Mika%2F42?filter=%3Cactive%3E",
    )


def test_mount_tokens_round_trip_action() -> None:
    codec = MountTokenCodec("s" * 32, max_age_ms=60_000)
    token = codec.sign(
        "tests.CounterLive", {}, "/counter", "index", "team", now_ms=1_000_000
    )

    assert codec.verify(token, now_ms=1_030_000) == MountToken(
        "tests.CounterLive",
        "index",
        "team",
        {},
        "/counter",
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


def test_mount_tokens_carry_the_disconnected_flash() -> None:
    codec = MountTokenCodec("s" * 32, max_age_ms=60_000)
    token = codec.sign(
        "Counter", {}, "/counter", flash={"info": "Saved"}, now_ms=1_000_000
    )
    assert codec.verify(token, now_ms=1_000_000).flash == {"info": "Saved"}
    plain = codec.sign("Counter", {}, "/counter", flash={}, now_ms=1_000_000)
    assert codec.verify(plain, now_ms=1_000_000).flash == {}


def test_flash_tokens_round_trip_expire_and_never_verify_as_mount_tokens() -> None:
    flash = FlashTokenCodec("s" * 32)
    mount = MountTokenCodec("s" * 32, max_age_ms=60_000)
    token = flash.sign({"info": "Moved", "error": ""}, now_ms=1_000_000)

    assert flash.verify(token, now_ms=1_060_000) == {"info": "Moved", "error": ""}
    assert flash.verify(token, now_ms=1_060_001) == {}
    assert flash.verify(token, now_ms=969_999) == {}
    payload, signature = token.split(".")
    assert flash.verify(f"{payload}A.{signature}", now_ms=1_000_000) == {}
    for invalid in (None, 7, "", "a.b", "a.b.c"):
        assert flash.verify(invalid, now_ms=1_000_000) == {}
    assert FlashTokenCodec("t" * 32).verify(token, now_ms=1_000_000) == {}

    # The HMAC purpose separates the two token kinds under one secret.
    with pytest.raises(InvalidMountTokenError):
        mount.verify(token, now_ms=1_000_000)
    mount_token = mount.sign("Counter", {}, "/counter", now_ms=1_000_000)
    assert flash.verify(mount_token, now_ms=1_000_000) == {}

    with pytest.raises(ValueError, match="32 bytes"):
        FlashTokenCodec("short")
    with pytest.raises(ValueError, match="positive integer"):
        FlashTokenCodec("s" * 32, max_age_ms=0)


def test_reload_tokens_bind_a_client_error_to_one_page_and_resource() -> None:
    reload = ReloadTokenCodec("s" * 32)
    token = reload.sign("pages.Article", "/articles/1?tab=a", 404, now_ms=1_000_000)

    def verify(value: object, page: str, resource: str, now_ms: int) -> int | None:
        return reload.verify(value, page, resource, now_ms=now_ms)

    assert verify(token, "pages.Article", "/articles/1?tab=a", 1_060_000) == 404
    assert verify(token, "pages.Article", "/articles/1?tab=a", 1_060_001) is None
    assert verify(token, "pages.Other", "/articles/1?tab=a", 1_000_000) is None
    assert verify(token, "pages.Article", "/articles/1", 1_000_000) is None
    for status in (302, 500):
        server_error = reload.sign("pages.Article", "/", status, now_ms=1_000_000)
        assert verify(server_error, "pages.Article", "/", 1_000_000) is None
    for invalid in (None, 404, "", "a.b"):
        assert verify(invalid, "pages.Article", "/", 1_000_000) is None

    flash = FlashTokenCodec("s" * 32).sign({"info": "x"}, now_ms=1_000_000)
    assert verify(flash, "pages.Article", "/", 1_000_000) is None
    assert FlashTokenCodec("s" * 32).verify(token, now_ms=1_000_000) == {}
    with pytest.raises(InvalidMountTokenError):
        MountTokenCodec("s" * 32).verify(token, now_ms=1_000_000)


def test_child_tokens_bind_a_child_view_to_its_parent() -> None:
    child = ChildTokenCodec("s" * 32, max_age_ms=60_000)
    token = child.sign(
        "pages.Cart",
        "cart",
        "tori-live-root",
        {"store": "kyiv"},
        "/shop?tab=a",
        "shop",
        now_ms=1_000_000,
    )

    assert child.verify(token, now_ms=1_060_000) == ChildToken(
        "pages.Cart", "cart", "tori-live-root", {"store": "kyiv"}, "/shop?tab=a", "shop"
    )
    with pytest.raises(InvalidMountTokenError):
        child.verify(token, now_ms=1_060_001)
    with pytest.raises(InvalidMountTokenError):
        child.verify(token, now_ms=969_999)
    encoded, signature = token.split(".")
    for invalid in (None, "", f"{encoded}x.{signature}", f"{encoded}.{'0' * 64}"):
        with pytest.raises(InvalidMountTokenError):
            child.verify(invalid, now_ms=1_000_000)

    # Child and mount tokens never verify as each other.
    with pytest.raises(InvalidMountTokenError):
        MountTokenCodec("s" * 32).verify(token, now_ms=1_000_000)
    mount = MountTokenCodec("s" * 32).sign("pages.Cart", {}, "/", now_ms=1_000_000)
    with pytest.raises(InvalidMountTokenError):
        child.verify(mount, now_ms=1_000_000)


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
    for deadline in (0, -1, True, "5", float("nan"), float("inf")):
        with pytest.raises(LiveViewConfigurationError, match="async cancel timeout"):
            LiveViewOptions(
                secret="s" * 32, async_cancel_timeout_seconds=cast(Any, deadline)
            )
    assert LiveViewOptions(secret="s" * 32).async_cancel_timeout_seconds == 5.0
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


def test_options_normalize_redirect_hosts_to_bare_host_names() -> None:
    options = LiveViewOptions(secret="s" * 32, redirect_hosts=("IdP.Example",))
    assert options.redirect_hosts == ("idp.example",)

    with pytest.raises(LiveViewConfigurationError, match="must be a tuple"):
        LiveViewOptions(secret="s" * 32, redirect_hosts=cast(Any, ["idp.example"]))
    for host in (
        "",
        "https://idp.example",
        "idp.example:443",
        "idp.example/login",
        "user@idp.example",
    ):
        with pytest.raises(LiveViewConfigurationError, match="bare host names"):
            LiveViewOptions(secret="s" * 32, redirect_hosts=(host,))
