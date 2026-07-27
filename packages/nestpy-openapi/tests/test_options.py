from dataclasses import FrozenInstanceError
from types import MappingProxyType
from typing import Any, cast

import pytest
from nestpy_openapi import (
    BearerSecurityScheme,
    OpenApiConfigurationError,
    OpenApiInfo,
    OpenApiOptions,
    OpenApiServer,
    SwaggerUiOptions,
)


def test_values_are_frozen_slotted_and_have_value_semantics() -> None:
    info = OpenApiInfo("Example", "1.0", "Description")
    assert info == OpenApiInfo("Example", "1.0", "Description")
    assert repr(info) == (
        "OpenApiInfo(title='Example', version='1.0', description='Description')"
    )
    assert not hasattr(info, "__dict__")
    with pytest.raises(FrozenInstanceError):
        info.title = "Changed"  # type: ignore[misc]


def test_options_copy_iterables_and_disable_docs_with_none() -> None:
    servers = [OpenApiServer("https://api.example.test")]
    schemes = [BearerSecurityScheme("oidc")]
    options = OpenApiOptions(
        OpenApiInfo("Example", "1.0"),
        docs_path=None,
        servers=cast(Any, servers),
        security_schemes=cast(Any, schemes),
    )
    servers.append(OpenApiServer("https://other.example.test"))
    schemes.append(BearerSecurityScheme("other"))
    assert options.docs_path is None
    assert options.servers == (OpenApiServer("https://api.example.test"),)
    assert options.security_schemes == (BearerSecurityScheme("oidc"),)


def test_swagger_parameters_are_validated_and_defensively_deep_frozen() -> None:
    nested = {"persistAuthorization": True, "layout": {"items": ["one"]}}
    options = SwaggerUiOptions(parameters=nested)
    nested["persistAuthorization"] = False
    cast(dict[str, object], nested["layout"])["items"] = ["changed"]
    assert isinstance(options.parameters, MappingProxyType)
    assert options.parameters["persistAuthorization"] is True
    layout = cast(dict[str, object], options.parameters["layout"])
    assert isinstance(layout, MappingProxyType)
    assert layout["items"] == ("one",)
    with pytest.raises(TypeError):
        options.parameters["new"] = True  # type: ignore[index]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", ""),
        ("title", "   "),
        ("title", 1),
        ("version", ""),
        ("version", None),
        ("description", 1),
    ],
)
def test_invalid_info_values_are_rejected(field: str, value: object) -> None:
    values: dict[str, object] = {"title": "Example", "version": "1.0"}
    values[field] = value
    with pytest.raises(OpenApiConfigurationError):
        OpenApiInfo(**cast(Any, values))


@pytest.mark.parametrize(
    "path",
    [
        "",
        "docs",
        "//docs",
        "/docs?theme=dark",
        "/docs#section",
        "/{name}",
        "/{name:str}",
        "/docs\\index",
        "/docs index",
    ],
)
def test_invalid_endpoint_path_shapes_are_rejected(path: str) -> None:
    with pytest.raises(
        OpenApiConfigurationError,
        match="absolute static path|must not be empty",
    ):
        OpenApiOptions(OpenApiInfo("Example", "1.0"), docs_path=path)
    with pytest.raises(
        OpenApiConfigurationError,
        match="absolute static path|must not be empty",
    ):
        OpenApiOptions(OpenApiInfo("Example", "1.0"), openapi_path=path)


@pytest.mark.parametrize("path", ["/", "/docs", "/docs/", "/v1.open-api.json"])
def test_valid_endpoint_path_shapes_are_accepted(path: str) -> None:
    options = OpenApiOptions(
        OpenApiInfo("Example", "1.0"),
        docs_path=None,
        openapi_path=path,
    )
    assert options.openapi_path == path


def test_docs_and_openapi_paths_must_be_distinct() -> None:
    with pytest.raises(OpenApiConfigurationError, match="must be distinct"):
        OpenApiOptions(
            OpenApiInfo("Example", "1.0"),
            docs_path="/same",
            openapi_path="/same",
        )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "swagger.js",
        "//cdn.example.test/swagger.js",
        "http://cdn.example.test/swagger.js",
        "data:text/javascript,alert(1)",
        "javascript:alert(1)",
        "ftp://cdn.example.test/swagger.js",
        "https:///swagger.js",
        "https://cdn.example.test:bad/swagger.js",
        "https://cdn.example.test/%zz",
        r"/\evil.example/swagger.js",
        r"https://cdn.example.test\swagger.js",
    ],
)
def test_invalid_swagger_asset_urls_are_rejected(url: str) -> None:
    with pytest.raises(OpenApiConfigurationError):
        SwaggerUiOptions(javascript_url=url)
    with pytest.raises(OpenApiConfigurationError):
        SwaggerUiOptions(stylesheet_url=url)


@pytest.mark.parametrize(
    "url",
    [
        "/assets/swagger.js",
        "/assets/swagger.js?v=1",
        "https://cdn.example.test/swagger.js",
        "https://cdn.example.test/swagger.js?v=1",
    ],
)
def test_valid_swagger_asset_urls_are_accepted(url: str) -> None:
    options = SwaggerUiOptions(javascript_url=url, stylesheet_url=url)
    assert options.javascript_url == url
    assert options.stylesheet_url == url


@pytest.mark.parametrize(
    "url",
    [
        "",
        "https://",
        "://bad",
        "https://api.example.test:bad/v1",
        "https://api.example.test/with space",
        "https://api.example.test/%zz",
        "https://{tenant}.example.test",
        "line\nbreak",
        r"/api\v1",
    ],
)
def test_invalid_server_urls_are_rejected(url: str) -> None:
    with pytest.raises(OpenApiConfigurationError):
        OpenApiServer(url)


@pytest.mark.parametrize(
    "url",
    ["/v1", "api/v1", "https://api.example.test", "http://localhost:8000/v1"],
)
def test_valid_server_urls_are_accepted(url: str) -> None:
    assert OpenApiServer(url).url == url


@pytest.mark.parametrize("key", ["url", "urls", "spec", "dom_id"])
def test_reserved_swagger_parameters_are_rejected(key: str) -> None:
    with pytest.raises(OpenApiConfigurationError, match="reserved"):
        SwaggerUiOptions(parameters={key: "value"})


def test_non_json_swagger_parameters_are_rejected() -> None:
    with pytest.raises(OpenApiConfigurationError, match="JSON encodable"):
        SwaggerUiOptions(parameters={"plugin": object()})


@pytest.mark.parametrize("name", ["", "with space", "slash/name", "oidc@issuer"])
def test_invalid_security_scheme_names_are_rejected(name: str) -> None:
    with pytest.raises(OpenApiConfigurationError):
        BearerSecurityScheme(name)


def test_duplicate_security_scheme_names_are_rejected() -> None:
    with pytest.raises(OpenApiConfigurationError, match="must be unique"):
        OpenApiOptions(
            OpenApiInfo("Example", "1.0"),
            security_schemes=(
                BearerSecurityScheme("oidc"),
                BearerSecurityScheme("oidc"),
            ),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("info", object(), "OpenApiInfo"),
        ("servers", [object()], "OpenApiServer"),
        ("security_schemes", [object()], "BearerSecurityScheme"),
        ("swagger_ui", object(), "SwaggerUiOptions"),
    ],
)
def test_wrong_option_types_are_rejected(
    field: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {"info": OpenApiInfo("Example", "1.0")}
    values[field] = value
    with pytest.raises(OpenApiConfigurationError, match=message):
        OpenApiOptions(**cast(Any, values))
