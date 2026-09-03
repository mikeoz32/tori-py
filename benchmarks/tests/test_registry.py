from __future__ import annotations

from tori_py_benchmarks.registry import FRAMEWORKS, SCENARIOS


def test_registry_contains_the_mvp_competitors_in_stable_order() -> None:
    assert [framework.name for framework in FRAMEWORKS] == [
        "raw-asgi",
        "starlette",
        "fastapi",
        "litestar",
        "tori-py-starlette",
        "tori-py-asgi",
    ]
    assert len({framework.module for framework in FRAMEWORKS}) == len(FRAMEWORKS)
    assert SCENARIOS == {
        "plaintext": b"Hello, World!",
        "json": {"message": "Hello, World!"},
        "singleton": {"value": 5},
        "inject": {"value": 5},
    }


def test_framework_registry_names_installed_distributions() -> None:
    assert [framework.distribution for framework in FRAMEWORKS] == [
        None,
        "starlette",
        "fastapi",
        "litestar",
        "tori-py-framework",
        "tori-py-framework",
    ]
