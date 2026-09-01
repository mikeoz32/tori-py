"""Authorization predicates shared by the workplace process boundaries."""

from .contracts import Principal

WORKPLACE_ROLES = frozenset({"employee", "facilities-admin"})


def has_workplace_role(principal: Principal) -> bool:
    return not WORKPLACE_ROLES.isdisjoint(principal.roles)


def is_facilities_admin(principal: Principal) -> bool:
    return "facilities-admin" in principal.roles
