"""Smoke-test nestpy-microservices wheel and source distributions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMOKE = r"""
import sys

import nestpy_microservices
import nestpy_microservices.rabbitmq

assert set(nestpy_microservices.__all__) == {
    "EventEnvelope",
    "EventIdentity",
    "EventDispatchMode",
    "EventContext",
    "EventHandlerMetadata",
    "EventHandlerPlan",
    "IdentityValidationError",
    "Context",
    "HandlerCompilationError",
    "Header",
    "Headers",
    "Inject",
    "MessageCodec",
    "MessageContext",
    "MessageLimits",
    "MessageMetadata",
    "MessageParameterPlan",
    "MicroservicesError",
    "MsgspecJsonMessageCodec",
    "OptionalDependencyError",
    "Payload",
    "PipelinePlan",
    "RESULT_MISSING",
    "RemoteRpcErrorData",
    "ReplyRoute",
    "RpcRequestEnvelope",
    "RpcResponseEnvelope",
    "RpcHandlerPlan",
    "RpcMetadata",
    "RpcContext",
    "RpcTarget",
    "ServiceIdentity",
    "ServiceHandlerRegistry",
    "WireDeadlineError",
    "WireDecodingError",
    "WireEncodingError",
    "WireSizeLimitError",
    "WireValidationError",
    "require_future_deadline",
    "require_uuid",
    "require_utc",
    "utc_now",
    "validate_alias",
    "validate_version",
    "compile_controller_message_handlers",
    "compile_discovered_service_handlers",
    "compile_service_handler_registry",
    "event_handler",
    "rpc",
}
assert "aio_pika" not in sys.modules
assert "starlette" not in sys.modules
assert "sqlalchemy" not in sys.modules
"""


def _one(dist: Path, pattern: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(
            f"expected one {pattern} artifact in {dist}, found {len(matches)}"
        )
    return matches[0]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    dist = Path(sys.argv[1]).resolve()
    artifact_sets = (
        (
            _one(dist, "nestpy-0.1.0-*.whl"),
            _one(dist, "nestpy_microservices-*.whl"),
        ),
        (
            _one(dist, "nestpy-0.1.0.tar.gz"),
            _one(dist, "nestpy_microservices-*.tar.gz"),
        ),
    )
    for artifacts in artifact_sets:
        command = ["uv", "run", "--isolated", "--no-project"]
        for artifact in artifacts:
            command.extend(("--with", str(artifact)))
        command.extend(("python", "-c", SMOKE))
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifacts[-1].name}")


if __name__ == "__main__":
    main()
