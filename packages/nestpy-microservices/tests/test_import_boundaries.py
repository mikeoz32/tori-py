from __future__ import annotations

import subprocess
import sys


def test_base_import_does_not_load_forbidden_modules() -> None:
    script = """
import sys
import nestpy_microservices
import nestpy_microservices.rabbitmq

for name in (
    "aio_pika",
    "starlette",
    "sqlalchemy",
    "cqrs_core",
    "cqrs_event_sourcing",
    "kinker",
):
    assert name not in sys.modules, name
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_missing_rabbitmq_extra_has_actionable_error() -> None:
    script = """
import builtins
import importlib

import nestpy_microservices.rabbitmq as rabbitmq
import nestpy_microservices.rabbitmq.dependencies as dependencies
from nestpy_microservices import OptionalDependencyError

real_import = builtins.__import__
real_import_module = importlib.import_module

def blocked_import(name, *args, **kwargs):
    if name == "aio_pika":
        raise ModuleNotFoundError("blocked for boundary test", name="aio_pika")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked_import
def blocked_import_module(name, package=None):
    if name == "aio_pika":
        raise ModuleNotFoundError("blocked for boundary test", name="aio_pika")
    return real_import_module(name, package)

importlib.import_module = blocked_import_module
dependencies.import_module = blocked_import_module
try:
    rabbitmq.require_aio_pika()
except OptionalDependencyError as error:
    assert error.dependency == "aio-pika"
    assert error.extra == "rabbitmq"
    assert "nestpy-microservices[rabbitmq]" in str(error)
else:
    raise AssertionError("expected OptionalDependencyError")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
