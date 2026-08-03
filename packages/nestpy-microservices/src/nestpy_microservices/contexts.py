"""Transport-neutral context protocols used by message handler annotations."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from nestpy import ExecutionContext


@runtime_checkable
class MessageContext(ExecutionContext, Protocol):
    """Common protocol implemented by RPC and event execution contexts."""


@runtime_checkable
class RpcContext(MessageContext, Protocol):
    """Context annotation accepted by RPC handlers."""


@runtime_checkable
class EventContext(MessageContext, Protocol):
    """Context annotation accepted by event handlers."""


__all__ = ["EventContext", "MessageContext", "RpcContext"]
