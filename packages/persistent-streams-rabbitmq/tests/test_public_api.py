from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import persistent_streams_rabbitmq


def test_rps0_package_boundary_is_exact() -> None:
    root = Path(__file__).parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))

    assert project["project"]["requires-python"] == ">=3.14,<3.15"
    assert project["project"]["dependencies"] == [
        "nestpy-persistent-streams",
        "persistent-streams",
        "rstream==1.0.1",
    ]
    assert (root / "README.md").is_file()
    assert (root / "src/persistent_streams_rabbitmq/py.typed").is_file()
    assert persistent_streams_rabbitmq.__all__ == [
        "CONTENT_TYPE",
        "DeclarationMode",
        "EnvelopeError",
        "EnvelopeLimits",
        "RABBITMQ_START_MODE_CAPABILITIES",
        "RabbitMqConnectionOptions",
        "RabbitMqPartitionLease",
        "RabbitMqPersistentLog",
        "RabbitMqPersistentStreamsError",
        "RabbitMqPersistentStreamsModule",
        "RabbitMqPersistentStreamsOptions",
        "RabbitMqStreamAdapterFactory",
        "RabbitMqTlsOptions",
        "RecordEnvelope",
        "SaslMechanism",
        "TopologyConflictError",
        "TopologyPreflight",
        "decode_amqp_message",
        "decode_envelope",
        "encode_amqp_message",
        "encode_envelope",
    ]


def test_root_import_is_lazy_and_performs_no_driver_import_or_io() -> None:
    script = """
import socket
import sys

def forbidden(*args, **kwargs):
    raise AssertionError("package import attempted network I/O")

socket.create_connection = forbidden
socket.socket.connect = forbidden
import persistent_streams_rabbitmq
assert persistent_streams_rabbitmq.__all__
assert 'rstream' not in sys.modules
assert 'persistent_streams' not in sys.modules
assert 'nestpy_persistent_streams' not in sys.modules
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
