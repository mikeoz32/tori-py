"""Stable framework and scenario registry used by reports."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Framework:
    name: str
    module: str
    distribution: str | None


FRAMEWORKS = (
    Framework("raw-asgi", "tori_py_benchmarks.apps.raw_asgi", None),
    Framework("starlette", "tori_py_benchmarks.apps.starlette_app", "starlette"),
    Framework("fastapi", "tori_py_benchmarks.apps.fastapi_app", "fastapi"),
    Framework("litestar", "tori_py_benchmarks.apps.litestar_app", "litestar"),
    Framework(
        "tori-py-starlette",
        "tori_py_benchmarks.apps.tori_py_app",
        "tori-py-framework",
    ),
    Framework(
        "tori-py-asgi",
        "tori_py_benchmarks.apps.tori_py_asgi_app",
        "tori-py-framework",
    ),
)

SCENARIOS: dict[str, bytes | dict[str, str] | dict[str, int]] = {
    "plaintext": b"Hello, World!",
    "json": {"message": "Hello, World!"},
    "singleton": {"value": 5},
    "inject": {"value": 5},
}


__all__ = ["FRAMEWORKS", "SCENARIOS", "Framework"]
