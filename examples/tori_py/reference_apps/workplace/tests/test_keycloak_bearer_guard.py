"""Negative authentication specifications for the Keycloak HTTP boundary."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast

import jwt
import pytest
from tori_py.http import HttpException

from examples.tori_py.reference_apps.workplace.gateway.app import KeycloakBearerGuard


class _Jwks:
    def get_signing_key_from_jwt(self, token: str) -> Any:
        del token
        return type("SigningKey", (), {"key": "public-key"})()


def _guard(jwks: _Jwks | None = None) -> KeycloakBearerGuard:
    return KeycloakBearerGuard(
        issuer="https://keycloak.example/realms/workplace",
        audience="tori-space-api",
        jwks_client=cast(Any, jwks or _Jwks()),
    )


def _claims(**overrides: object) -> dict[str, object]:
    claims: dict[str, object] = {
        "exp": 1_900_000_000,
        "iss": "https://keycloak.example/realms/workplace",
        "sub": "employee-1",
        "aud": "tori-space-api",
        "tenant_id": "tenant-north",
        "resource_access": {"tori-space-web": {"roles": ["employee"]}},
    }
    claims.update(overrides)
    return claims


def _assert_unauthorized(action: Callable[[], object]) -> None:
    with pytest.raises(HttpException) as error:
        action()
    assert error.value.status_code == 401


def test_missing_bearer_token_is_unauthorized() -> None:
    _assert_unauthorized(lambda: _guard().principal("Basic credentials"))


def test_invalid_signature_is_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            jwt.InvalidSignatureError("bad signature")
        ),
    )

    _assert_unauthorized(lambda: _guard().principal("Bearer forged"))


def test_decode_failure_is_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *args, **kwargs: (_ for _ in ()).throw(jwt.DecodeError("malformed")),
    )

    _assert_unauthorized(lambda: _guard().principal("Bearer malformed"))


@pytest.mark.parametrize("claim", ("exp", "iss", "sub", "aud"))
def test_missing_required_jwt_claim_is_unauthorized(
    monkeypatch: pytest.MonkeyPatch, claim: str
) -> None:
    def decode(*args: object, **kwargs: object) -> dict[str, object]:
        assert kwargs["options"] == {"require": ["exp", "iss", "sub", "aud"]}
        raise jwt.MissingRequiredClaimError(claim)

    monkeypatch.setattr(jwt, "decode", decode)

    _assert_unauthorized(lambda: _guard().principal("Bearer token"))


def test_missing_tenant_claim_is_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(jwt, "decode", lambda *args, **kwargs: _claims(tenant_id=None))

    _assert_unauthorized(lambda: _guard().principal("Bearer token"))


@pytest.mark.parametrize(
    "error",
    (
        jwt.InvalidAudienceError("wrong audience"),
        jwt.InvalidIssuerError("wrong issuer"),
    ),
)
def test_wrong_audience_or_issuer_is_unauthorized(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    _assert_unauthorized(lambda: _guard().principal("Bearer token"))


def test_realm_and_other_client_admin_roles_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        jwt,
        "decode",
        lambda *args, **kwargs: _claims(
            realm_access={"roles": ["facilities-admin"]},
            resource_access={
                "other-client": {"roles": ["facilities-admin"]},
                "tori-space-web": {"roles": ["employee"]},
            },
        ),
    )

    assert _guard().principal("Bearer token").roles == ("employee",)
