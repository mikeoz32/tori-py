from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest
from nestpy_openapi import (
    OpenApiMetadataError,
    api_exclude,
    api_operation,
    api_public,
    api_response,
    api_security,
    api_tags,
)
from nestpy_openapi.metadata import get_direct_metadata, merge_metadata


def test_decorators_preserve_target_identity_and_store_frozen_direct_metadata() -> None:
    class Controller:
        pass

    async def route() -> None:
        pass

    assert api_tags("controller")(Controller) is Controller
    assert api_operation(summary="Read")(route) is route
    metadata = get_direct_metadata(route)
    assert metadata.operation is not None
    assert metadata.operation.summary == "Read"
    with pytest.raises(FrozenInstanceError):
        metadata.public = True  # type: ignore[invalid-assignment]


def test_direct_lookup_does_not_inherit_class_metadata() -> None:
    @api_tags("base")
    class Base:
        pass

    class Child(Base):
        pass

    assert get_direct_metadata(Base).tags == ("base",)
    assert get_direct_metadata(Child).tags is None


def test_tags_merge_controller_then_route_and_deduplicate_stably() -> None:
    @api_tags("members", "shared")
    class Controller:
        @api_tags("shared", "detail", "detail")
        async def route(self) -> None:
            pass

    merged = merge_metadata(Controller, Controller.route)
    assert merged.tags == ("members", "shared", "detail")


def test_response_stacking_preserves_visible_source_order() -> None:
    @api_response(400, description="first")
    @api_response(404, description="second", model=dict[str, str])
    async def route() -> None:
        pass

    responses = get_direct_metadata(route).responses
    assert [response.status_code for response in responses] == [400, 404]
    assert responses[0].has_model is False
    assert responses[1].has_model is True
    assert responses[1].model == dict[str, str]


def test_route_responses_override_controller_status_and_append_new_statuses() -> None:
    @api_response(400, description="controller bad request")
    @api_response(404, description="controller missing")
    class Controller:
        @api_response(400, description="route bad request")
        @api_response(422, description="route invalid")
        async def route(self) -> None:
            pass

    responses = merge_metadata(Controller, Controller.route).responses
    assert [response.status_code for response in responses] == [400, 404, 422]
    assert responses[0].description == "route bad request"


def test_security_stacking_is_stable_or_alternatives() -> None:
    @api_security("oidc", scopes=("read",))
    @api_security("service")
    class Controller:
        async def inherited(self) -> None:
            pass

        @api_security("admin")
        @api_security("support")
        async def overridden(self) -> None:
            pass

    inherited = merge_metadata(Controller, Controller.inherited)
    overridden = merge_metadata(Controller, Controller.overridden)
    assert [(item.name, item.scopes) for item in inherited.security] == [
        ("oidc", ("read",)),
        ("service", ()),
    ]
    assert [item.name for item in overridden.security] == ["admin", "support"]


def test_api_public_clears_inherited_security() -> None:
    @api_security("oidc")
    class Controller:
        @api_public()
        async def route(self) -> None:
            pass

    merged = merge_metadata(Controller, Controller.route)
    assert merged.public is True
    assert merged.security == ()


def test_controller_and_route_exclusion_are_distinct_but_both_merge() -> None:
    @api_exclude()
    class ExcludedController:
        async def route(self) -> None:
            pass

    class Controller:
        @api_exclude()
        async def excluded(self) -> None:
            pass

        async def included(self) -> None:
            pass

    assert merge_metadata(ExcludedController, ExcludedController.route).excluded
    assert merge_metadata(Controller, Controller.excluded).excluded
    assert not merge_metadata(Controller, Controller.included).excluded
    assert get_direct_metadata(Controller).excluded is False


def test_operation_values_and_route_precedence_are_exact() -> None:
    class Controller:
        @api_operation(
            summary="Read",
            description="Read one member",
            operation_id="members_read",
            deprecated=True,
        )
        async def route(self) -> None:
            pass

    operation = merge_metadata(Controller, Controller.route).operation
    assert operation is not None
    assert operation.summary == "Read"
    assert operation.description == "Read one member"
    assert operation.operation_id == "members_read"
    assert operation.deprecated is True


@pytest.mark.parametrize(
    "decorator",
    [
        api_tags("one"),
        api_operation(summary="one"),
        api_response(200),
        api_security("oidc"),
        api_public(),
        api_exclude(),
    ],
)
def test_invalid_decorator_targets_are_rejected(decorator: Any) -> None:
    with pytest.raises(OpenApiMetadataError, match="target"):
        decorator(object())


def test_route_only_decorators_reject_controller_classes() -> None:
    class Controller:
        pass

    with pytest.raises(OpenApiMetadataError, match="route function"):
        api_operation(summary="Invalid")(Controller)
    with pytest.raises(OpenApiMetadataError, match="route function"):
        api_public()(Controller)


@pytest.mark.parametrize("value", ["", "   ", 1, None])
def test_invalid_tags_are_rejected(value: object) -> None:
    with pytest.raises(OpenApiMetadataError):
        api_tags(cast(Any, value))


@pytest.mark.parametrize("value", ["", "   ", 1])
def test_invalid_operation_strings_are_rejected(value: object) -> None:
    with pytest.raises(OpenApiMetadataError):
        api_operation(operation_id=cast(Any, value))


@pytest.mark.parametrize("status_code", [True, "200", 99, 600])
def test_invalid_response_status_codes_are_rejected(status_code: object) -> None:
    with pytest.raises(OpenApiMetadataError):
        api_response(cast(Any, status_code))


@pytest.mark.parametrize(
    ("name", "scopes"),
    [
        ("", ()),
        ("   ", ()),
        ("oidc", "read"),
        ("oidc", ("",)),
        ("oidc", ("read", "read")),
        ("oidc", (1,)),
    ],
)
def test_invalid_security_names_and_scopes_are_rejected(
    name: object,
    scopes: object,
) -> None:
    with pytest.raises(OpenApiMetadataError):
        api_security(cast(Any, name), cast(Any, scopes))


def test_duplicate_singleton_and_repeatable_metadata_are_rejected() -> None:
    @api_tags("one")
    @api_operation(summary="one")
    @api_response(200)
    @api_security("oidc")
    @api_exclude()
    async def route() -> None:
        pass

    with pytest.raises(OpenApiMetadataError, match="tags"):
        api_tags("two")(route)
    with pytest.raises(OpenApiMetadataError, match="operation"):
        api_operation(summary="two")(route)
    with pytest.raises(OpenApiMetadataError, match="response status"):
        api_response(200)(route)
    with pytest.raises(OpenApiMetadataError, match="security requirement"):
        api_security("oidc")(route)
    with pytest.raises(OpenApiMetadataError, match="api_exclude"):
        api_exclude()(route)


def test_public_and_route_security_conflict_in_either_decorator_order() -> None:
    @api_public()
    async def public_first() -> None:
        pass

    @api_security("oidc")
    async def security_first() -> None:
        pass

    with pytest.raises(OpenApiMetadataError, match="cannot be combined"):
        api_security("oidc")(public_first)
    with pytest.raises(OpenApiMetadataError, match="cannot be combined"):
        api_public()(security_first)
