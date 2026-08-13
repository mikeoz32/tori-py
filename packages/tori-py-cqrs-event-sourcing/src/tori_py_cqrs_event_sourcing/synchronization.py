"""Command-side external-effect synchronization contracts."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from tori_py_cqrs_event_sourcing_core import CommitResult

type Finalizer = Callable[[], Awaitable[None] | None]
type CommitCallback = Callable[[CommitResult], Awaitable[None] | None]
type IndeterminateCallback = Callable[[BaseException], Awaitable[None] | None]


class CommandSynchronization(Protocol):
    """Register callbacks selected by the final persistence outcome."""

    def after_commit(self, callback: CommitCallback) -> None: ...

    def after_confirmed_non_commit(self, callback: Finalizer) -> None: ...

    def after_indeterminate(self, callback: IndeterminateCallback) -> None: ...


__all__ = ["CommandSynchronization"]
