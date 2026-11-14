"""Bearer-token authentication and role checks for the Task API."""

from dataclasses import dataclass
from typing import Protocol

from tori_py import ExecutionContext
from tori_py.http import HttpException
from tori_py.starlette import RequestContext

SIGN_IN = {"WWW-Authenticate": "Bearer"}
INVALID_TOKEN = {"WWW-Authenticate": 'Bearer error="invalid_token"'}


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    roles: frozenset[str] = frozenset()


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> Principal | None:
        """Return the principal for a valid token, or None."""
        ...


class DemoTokenVerifier:
    """Two fixed demonstration tokens.

    A real verifier checks a signed token from an identity provider, or asks
    that provider, and never compares against values stored in source code.
    """

    TOKENS = {
        "alice-token": Principal("alice", frozenset({"admin"})),
        "bob-token": Principal("bob"),
    }

    async def verify(self, token: str) -> Principal | None:
        return self.TOKENS.get(token)


class CurrentPrincipal:
    """The caller of one request, bound once by AuthenticationGuard."""

    def __init__(self) -> None:
        self._principal: Principal | None = None
        self._bound = False

    def bind(self, principal: Principal | None) -> None:
        if self._bound:
            raise RuntimeError("the principal is already bound")
        self._principal = principal
        self._bound = True

    @property
    def principal(self) -> Principal | None:
        """Return the caller, or None for an anonymous request."""

        if not self._bound:
            raise RuntimeError("AuthenticationGuard has not run")
        return self._principal

    def require(self) -> Principal:
        principal = self.principal
        if principal is None:
            raise HttpException(
                401,
                "Send a bearer token to do this.",
                title="Unauthorized",
                headers=SIGN_IN,
            )
        return principal


class AuthenticationGuard:
    """Identify the caller from an optional bearer token."""

    def __init__(self, verifier: TokenVerifier, current: CurrentPrincipal) -> None:
        self._verifier = verifier
        self._current = current

    async def can_activate(self, context: RequestContext) -> bool:
        header = context.headers.get("authorization")
        if header is None:
            self._current.bind(None)
            return True
        scheme, _, token = header.partition(" ")
        principal = None
        if scheme.lower() == "bearer" and token:
            principal = await self._verifier.verify(token)
        if principal is None:
            raise HttpException(
                401,
                "The bearer token is not valid.",
                title="Unauthorized",
                headers=INVALID_TOKEN,
            )
        self._current.bind(principal)
        return True


class RequireUser:
    """Allow only authenticated callers."""

    def __init__(self, current: CurrentPrincipal) -> None:
        self._current = current

    async def can_activate(self, context: ExecutionContext) -> bool:
        del context
        self._current.require()
        return True


class RequireAdmin:
    """Allow only callers with the admin role."""

    def __init__(self, current: CurrentPrincipal) -> None:
        self._current = current

    async def can_activate(self, context: ExecutionContext) -> bool:
        del context
        principal = self._current.principal
        return principal is not None and "admin" in principal.roles
