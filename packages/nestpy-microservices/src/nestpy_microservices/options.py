"""Validated transport-neutral service policy for the MS5 runtime."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from nestpy_microservices.identities import MessageLimits
from nestpy_microservices.plans import PipelinePlan


@dataclass(frozen=True, slots=True)
class MicroservicesOptions:
    """Finite service-wide limits and policy captured before application start."""

    max_concurrency: int = 32
    max_inflight_deliveries: int = 32
    max_accepted_rpc_timeout: float = 30.0
    message_limits: MessageLimits = field(default_factory=MessageLimits)
    global_pipeline: PipelinePlan = field(default_factory=PipelinePlan)
    instance_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.max_concurrency, int) or self.max_concurrency <= 0:
            raise ValueError("max_concurrency must be positive")
        if (
            not isinstance(self.max_inflight_deliveries, int)
            or self.max_inflight_deliveries <= 0
        ):
            raise ValueError("max_inflight_deliveries must be positive")
        if self.max_inflight_deliveries < self.max_concurrency:
            raise ValueError(
                "max_inflight_deliveries cannot be lower than max_concurrency"
            )
        if (
            not isinstance(self.max_accepted_rpc_timeout, (int, float))
            or isinstance(self.max_accepted_rpc_timeout, bool)
            or not math.isfinite(self.max_accepted_rpc_timeout)
            or self.max_accepted_rpc_timeout <= 0
        ):
            raise ValueError("max_accepted_rpc_timeout must be positive")
        if not isinstance(self.message_limits, MessageLimits):
            raise TypeError("message_limits must be MessageLimits")
        if not isinstance(self.global_pipeline, PipelinePlan):
            raise TypeError("global_pipeline must be PipelinePlan")
        if self.instance_id is not None and not self.instance_id:
            raise ValueError("instance_id must be non-empty when provided")


__all__ = ["MicroservicesOptions"]
