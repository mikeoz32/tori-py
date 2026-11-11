"""Keep the errors reference in step with public exceptions and codes."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

import pytest
from tori_py import DIAGNOSTIC_CODES

ROOT = Path(__file__).resolve().parents[4]
REFERENCE = ROOT / "docs" / "reference" / "errors-and-diagnostics.md"
FACADES = (
    "tori_py",
    "tori_py.http",
    "tori_py.websocket",
    "tori_py_cqrs_core",
    "tori_py_cqrs",
    "tori_py_cqrs_fastapi",
    "tori_py_cqrs_event_sourcing_core",
    "tori_py_cqrs_event_sourcing",
    "tori_py_sqlalchemy",
    "tori_py_openapi",
    "tori_py_microservices",
    "tori_py_persistent_streams_core",
    "tori_py_persistent_streams",
    "tori_py_persistent_streams_rabbitmq",
    "tori_py_liveview",
    "tori_py_liveview_ui",
)
RAISED_CODE = re.compile(r'\bcode="([a-z_]+\.[a-z_]+)"')
MICROSERVICES_PREFIX = "microservices."


def _reference() -> str:
    return REFERENCE.read_text(encoding="utf-8")


def _public_exceptions(facade: str) -> list[type[BaseException]]:
    module = importlib.import_module(facade)
    exported = (getattr(module, name) for name in getattr(module, "__all__", ()))
    return [
        value
        for value in exported
        if isinstance(value, type) and issubclass(value, BaseException)
    ]


@pytest.mark.parametrize("facade", FACADES)
def test_every_public_exception_is_documented(facade: str) -> None:
    reference = _reference()
    missing = [
        error.__name__
        for error in _public_exceptions(facade)
        if f"`{error.__name__}`" not in reference
        and f"`{facade}.{error.__name__}`" not in reference
    ]
    assert missing == []


def test_every_default_exception_code_is_documented() -> None:
    reference = _reference()
    missing: list[str] = []
    for facade in FACADES:
        for error in _public_exceptions(facade):
            code = error.__dict__.get("diagnostic_code") or error.__dict__.get("code")
            if not isinstance(code, str):
                continue
            documented = code
            if code.startswith(MICROSERVICES_PREFIX):
                documented = code.removeprefix(MICROSERVICES_PREFIX)
            if f"`{documented}`" not in reference:
                missing.append(code)
    assert missing == []


def test_every_framework_diagnostic_code_is_documented() -> None:
    reference = _reference()
    raised = {
        code
        for path in (ROOT / "packages" / "tori-py" / "src").rglob("*.py")
        for code in RAISED_CODE.findall(path.read_text(encoding="utf-8"))
    }
    missing = sorted(
        code for code in DIAGNOSTIC_CODES | raised if f"`{code}`" not in reference
    )
    assert missing == []
