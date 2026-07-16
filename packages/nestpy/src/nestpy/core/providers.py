"""Explicit, immutable provider declarations."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum

from nestpy.core.errors import BootstrapError

type Token = type[object] | str
type ProviderFactory = Callable[..., object | Awaitable[object]]


class Scope(StrEnum):
    """Provider lifetime names accepted by the native container."""

    SINGLETON = "singleton"
    REQUEST = "request"
    TRANSIENT = "transient"


def validate_token(token: object) -> Token:
    if isinstance(token, str):
        if token:
            return token
    elif isinstance(token, type):
        return token
    raise BootstrapError(
        "provider token must be a class or non-empty string",
        code="provider.invalid_token",
    )


def normalize_scope(scope: Scope | str) -> Scope:
    try:
        return scope if isinstance(scope, Scope) else Scope(scope)
    except ValueError as error:
        raise BootstrapError(
            f"unsupported provider scope: {scope!r}",
            code="provider.invalid_scope",
        ) from error


@dataclass(frozen=True, slots=True)
class Inject:
    """Override an annotation's token inside ``typing.Annotated``."""

    token: Token

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", validate_token(self.token))


@dataclass(frozen=True, slots=True)
class ValueProvider:
    """Expose an explicit value, optionally as an owned resource."""

    token: Token
    value: object
    manage: bool = False
    scope: Scope = Scope.SINGLETON

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", validate_token(self.token))
        object.__setattr__(self, "scope", normalize_scope(self.scope))
        if self.scope is not Scope.SINGLETON:
            raise BootstrapError(
                "value providers can only have singleton scope",
                code="provider.invalid_scope",
            )
        if not isinstance(self.manage, bool):
            raise BootstrapError(
                "value provider manage must be boolean",
                code="provider.invalid_declaration",
            )


@dataclass(frozen=True, slots=True)
class ClassProvider:
    """Construct an explicit class through annotation-based DI."""

    token: Token
    use_class: type[object] | None = None
    scope: Scope = Scope.SINGLETON
    manage: bool = True

    def __post_init__(self) -> None:
        token = validate_token(self.token)
        target = self.use_class
        if target is None and isinstance(token, type):
            target = token
        if not isinstance(target, type):
            raise BootstrapError(
                "class provider requires a class target",
                code="provider.invalid_declaration",
            )
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "use_class", target)
        object.__setattr__(self, "scope", normalize_scope(self.scope))
        if not isinstance(self.manage, bool):
            raise BootstrapError(
                "class provider manage must be boolean",
                code="provider.invalid_declaration",
            )


@dataclass(frozen=True, slots=True)
class FactoryProvider:
    """Invoke an explicit sync or async factory through annotation-based DI."""

    token: Token
    factory: ProviderFactory
    scope: Scope = Scope.SINGLETON
    manage: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", validate_token(self.token))
        object.__setattr__(self, "scope", normalize_scope(self.scope))
        if not callable(self.factory):
            raise BootstrapError(
                "factory provider factory must be callable",
                code="provider.invalid_declaration",
            )
        if not isinstance(self.manage, bool):
            raise BootstrapError(
                "factory provider manage must be boolean",
                code="provider.invalid_declaration",
            )


@dataclass(frozen=True, slots=True)
class AliasProvider:
    """Expose an existing provider token without independent ownership."""

    token: Token
    target: Token

    def __post_init__(self) -> None:
        object.__setattr__(self, "token", validate_token(self.token))
        object.__setattr__(self, "target", validate_token(self.target))


type ProviderDeclaration = (
    ValueProvider | ClassProvider | FactoryProvider | AliasProvider
)


def provider_token(provider: ProviderDeclaration) -> Token:
    """Return a declaration's public token without resolving it."""

    return provider.token


__all__ = [
    "AliasProvider",
    "ClassProvider",
    "FactoryProvider",
    "Inject",
    "ProviderDeclaration",
    "ProviderFactory",
    "Scope",
    "Token",
    "ValueProvider",
    "normalize_scope",
    "provider_token",
    "validate_token",
]
