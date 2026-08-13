from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rstream import Producer


@dataclass(slots=True)
class PublisherSlot:
    """Lifetime-stable serialization and optional named producer resource."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    producer: Producer | None = None


__all__ = ["PublisherSlot"]
