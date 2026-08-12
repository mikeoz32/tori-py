from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("RPS0_RABBITMQ") == "1":
        return
    skip = pytest.mark.skip(reason="set RPS0_RABBITMQ=1 for disposable broker spikes")
    for item in items:
        if item.get_closest_marker("rabbitmq") is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def rabbitmq_connection() -> dict[str, object]:
    return {
        "host": os.environ.get("RPS0_RABBITMQ_HOST", "127.0.0.1"),
        "port": int(os.environ.get("RPS0_RABBITMQ_PORT", "5552")),
        "username": "streams",
        "password": "streams",
    }


@pytest.fixture(scope="session")
def rabbitmq_management_url() -> str:
    return "http://127.0.0.1:15672/api"
