"""Driver-neutral HTTP request-body streaming contracts."""

from collections.abc import AsyncIterator
from typing import Protocol


class HttpBodyStream(Protocol):
    """A request-lifetime, single-consumer stream of raw body byte chunks."""

    def __aiter__(self) -> AsyncIterator[bytes]: ...

    async def aclose(self) -> None:
        """Close the stream before request processing finishes."""

        ...


__all__ = ["HttpBodyStream"]
