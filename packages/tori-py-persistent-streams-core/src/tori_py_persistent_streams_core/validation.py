from __future__ import annotations

from tori_py_persistent_streams_core.errors import ResourceLimitError
from tori_py_persistent_streams_core.models import AppendRequest, StreamDefinition


def validate_append_request_limits(
    definition: StreamDefinition, request: AppendRequest
) -> None:
    """Validate an append against the limits fixed by its stream definition."""
    limits = definition.limits
    if len(request.partition_key) > limits.max_partition_key_bytes:
        raise ResourceLimitError("partition key exceeds stream limit")
    if len(request.payload) > limits.max_payload_bytes:
        raise ResourceLimitError("payload exceeds stream limit")
    if len(request.headers) > limits.max_headers:
        raise ResourceLimitError("header count exceeds stream limit")
    aggregate = 0
    for name, value in request.headers.items():
        if len(name) > limits.max_header_name_chars:
            raise ResourceLimitError("header name exceeds stream limit")
        if len(value) > limits.max_header_value_bytes:
            raise ResourceLimitError("header value exceeds stream limit")
        aggregate += len(name.encode()) + len(value)
    if aggregate > limits.max_header_bytes:
        raise ResourceLimitError("aggregate headers exceed stream limit")
    if (
        request.producer_name is not None
        and len(request.producer_name) > limits.max_producer_chars
    ):
        raise ResourceLimitError("producer_name exceeds stream limit")


__all__ = ["validate_append_request_limits"]
