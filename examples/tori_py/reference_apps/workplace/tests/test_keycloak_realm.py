"""Keycloak realm configuration contracts for the workplace browser."""

from __future__ import annotations

import json
from pathlib import Path


def test_web_client_accepts_every_published_browser_route() -> None:
    realm_path = Path(__file__).parents[1] / "keycloak" / "tori-space-realm.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    web_client = next(
        client for client in realm["clients"] if client["clientId"] == "tori-space-web"
    )

    assert set(web_client["redirectUris"]) == {
        "http://localhost:8010/web/",
        "http://127.0.0.1:8010/web/",
        "http://localhost:8010/live/workplace",
        "http://127.0.0.1:8010/live/workplace",
    }


def test_web_client_maps_username_into_browser_tokens() -> None:
    realm_path = Path(__file__).parents[1] / "keycloak" / "tori-space-realm.json"
    realm = json.loads(realm_path.read_text(encoding="utf-8"))
    web_client = next(
        client for client in realm["clients"] if client["clientId"] == "tori-space-web"
    )
    username_mapper = next(
        mapper
        for mapper in web_client["protocolMappers"]
        if mapper["config"].get("claim.name") == "preferred_username"
    )

    assert username_mapper["protocolMapper"] == "oidc-usermodel-property-mapper"
    assert username_mapper["config"]["user.attribute"] == "username"
    assert username_mapper["config"]["access.token.claim"] == "true"
