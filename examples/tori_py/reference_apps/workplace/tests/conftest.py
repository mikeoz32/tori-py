"""Platform-compatible event loops for workplace integration tests."""

from __future__ import annotations

import asyncio
import selectors
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture(scope="session")
def docker_compose_file() -> str:
    return str(Path(__file__).with_name("docker-compose.yml"))


@pytest.fixture
def postgres_url(docker_services, docker_ip: str) -> str:
    pytest.importorskip("psycopg")
    pytest.importorskip("pytest_docker")
    port = docker_services.port_for("postgres", 5432)
    url = f"postgresql+psycopg://postgres:postgres@{docker_ip}:{port}/postgres"
    readiness_url = f"postgresql://postgres:postgres@{docker_ip}:{port}/postgres"

    def is_ready() -> bool:
        psycopg = __import__("psycopg")

        try:
            with psycopg.connect(readiness_url):
                return True
        except psycopg.OperationalError:
            return False

    docker_services.wait_until_responsive(is_ready, timeout=30, pause=0.5)
    return url


def pytest_asyncio_loop_factories(
    config: Any, item: Any
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    del config, item
    if sys.platform == "win32":
        return {
            "selector": lambda: asyncio.SelectorEventLoop(selectors.SelectSelector())
        }
    return {"default": asyncio.new_event_loop}
