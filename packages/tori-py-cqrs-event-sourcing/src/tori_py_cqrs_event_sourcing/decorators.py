"""Repository and transactional-handler declarations."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast, overload

from tori_py import BootstrapError, Inject, Reflector, metadata
from tori_py_cqrs import (
    CqrsInterceptorBinding,
    CqrsInterceptorPhase,
    use_cqrs_interceptors,
)
from tori_py_cqrs_core import HandlerKind, get_handler_metadata
from tori_py_cqrs_event_sourcing_core import AggregateRoot, EventSourcedRepository

from tori_py_cqrs_event_sourcing.errors import CqrsEventSourcingConfigurationError
from tori_py_cqrs_event_sourcing.tokens import get_transaction_interceptor_token


@dataclass(frozen=True, slots=True)
class _AggregateRepositoryMetadata:
    aggregate_type: type[AggregateRoot[Any]]
    category: str
    id_encoder: Callable[[object], str]
    aggregate_factory: Callable[[object], AggregateRoot[Any]]
    page_size: int | None


_AGGREGATE_REPOSITORY = Reflector.create_decorator(
    "tori_py_cqrs_event_sourcing.aggregate_repository"
)
_REFLECTOR = Reflector()
_UNSET = object()


@overload
def aggregate_repository[
    AggregateT: AggregateRoot[Any],
    RepositoryT: EventSourcedRepository[Any, Any],
](
    target: type[AggregateT],
    *,
    category: str,
    id_encoder: Callable[[object], str] = str,
    aggregate_factory: Callable[[object], AggregateT] | None = None,
    page_size: int | None = None,
) -> Callable[
    [type[RepositoryT]],
    type[RepositoryT],
]: ...


@overload
def aggregate_repository[
    RepositoryT: EventSourcedRepository[Any, Any],
](target: type[RepositoryT]) -> Inject: ...


def aggregate_repository(
    target: type[object],
    *,
    category: str | None | object = _UNSET,
    id_encoder: Callable[[object], str] | None | object = _UNSET,
    aggregate_factory: Callable[[object], object] | None | object = _UNSET,
    page_size: int | None | object = _UNSET,
) -> Callable[[type[object]], type[object]] | Inject:
    """Declare a repository class or create its standard ToriPy Inject marker."""

    if isinstance(target, type) and issubclass(target, EventSourcedRepository):
        if any(
            value is not _UNSET
            for value in (category, id_encoder, aggregate_factory, page_size)
        ):
            raise CqrsEventSourcingConfigurationError(
                "repository injection form does not accept declaration options"
            )
        if not _REFLECTOR.has_own(_AGGREGATE_REPOSITORY, target):
            raise CqrsEventSourcingConfigurationError(
                "repository injection requires a directly decorated repository"
            )
        return Inject(target)

    if (
        not isinstance(target, type)
        or target is AggregateRoot
        or not issubclass(target, AggregateRoot)
        or inspect.isabstract(target)
    ):
        raise CqrsEventSourcingConfigurationError(
            "aggregate must be a concrete AggregateRoot subclass"
        )
    if not isinstance(category, str) or not category or category != category.strip():
        raise CqrsEventSourcingConfigurationError(
            "repository category must be a non-empty trimmed string"
        )
    selected_encoder = cast(
        Callable[[object], str],
        str if id_encoder is _UNSET or id_encoder is None else id_encoder,
    )
    selected_factory = cast(
        Callable[[object], AggregateRoot[Any]],
        (
            target
            if aggregate_factory is _UNSET or aggregate_factory is None
            else aggregate_factory
        ),
    )
    if not callable(selected_encoder) or not callable(selected_factory):
        raise CqrsEventSourcingConfigurationError(
            "repository ID encoder and aggregate factory must be callable"
        )
    selected_page_size = None if page_size is _UNSET else page_size
    if selected_page_size is not None and (
        not isinstance(selected_page_size, int)
        or isinstance(selected_page_size, bool)
        or selected_page_size < 1
    ):
        raise CqrsEventSourcingConfigurationError(
            "repository page_size must be a positive integer or None"
        )
    declaration = _AggregateRepositoryMetadata(
        aggregate_type=target,
        category=category,
        id_encoder=selected_encoder,
        aggregate_factory=selected_factory,
        page_size=selected_page_size,
    )

    def decorate(repository: type[object]) -> type[object]:
        if (
            not isinstance(repository, type)
            or repository is EventSourcedRepository
            or not issubclass(repository, EventSourcedRepository)
            or inspect.isabstract(repository)
        ):
            raise CqrsEventSourcingConfigurationError(
                "repository must be a concrete EventSourcedRepository subclass"
            )
        if _REFLECTOR.has(_AGGREGATE_REPOSITORY, repository):
            raise CqrsEventSourcingConfigurationError(
                "repository metadata must be declared directly and only once"
            )
        try:
            return metadata(_AGGREGATE_REPOSITORY, declaration)(repository)
        except BootstrapError as error:
            raise CqrsEventSourcingConfigurationError(
                "invalid aggregate repository declaration"
            ) from error

    return decorate


def use_event_sourcing[TargetT](
    *, key: str = "default"
) -> Callable[[TargetT], TargetT]:
    """Bind one decorated command handler to the keyed outer transaction."""

    binding = event_sourcing_transaction(key=key)

    def decorate(target: TargetT) -> TargetT:
        handler = get_handler_metadata(target)
        if handler is None or handler.kind is not HandlerKind.COMMAND:
            raise CqrsEventSourcingConfigurationError(
                "use_event_sourcing requires an already decorated command handler"
            )
        return use_cqrs_interceptors(
            binding,
        )(target)

    return decorate


def event_sourcing_transaction(
    *,
    key: str = "default",
) -> CqrsInterceptorBinding:
    """Return a command-only outer binding for explicit factory handlers."""

    return CqrsInterceptorBinding(
        get_transaction_interceptor_token(key=key),
        CqrsInterceptorPhase.OUTER,
        handler_kinds=(HandlerKind.COMMAND,),
    )


def _repository_metadata(
    repository: type[EventSourcedRepository[Any, Any]],
) -> _AggregateRepositoryMetadata:
    declaration = _REFLECTOR.get_own(_AGGREGATE_REPOSITORY, repository)
    if not isinstance(declaration, _AggregateRepositoryMetadata):
        if _REFLECTOR.has(_AGGREGATE_REPOSITORY, repository):
            message = "inherited repository metadata is not accepted"
        else:
            message = "repository must be directly decorated"
        raise CqrsEventSourcingConfigurationError(message)
    return declaration


__all__ = [
    "aggregate_repository",
    "event_sourcing_transaction",
    "use_event_sourcing",
]
