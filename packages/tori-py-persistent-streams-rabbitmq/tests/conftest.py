from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class RabbitMqCompose:
    command: tuple[str, ...]
    root: Path

    def run(
        self,
        *arguments: str,
        check: bool = True,
        timeout: float = 180,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [*self.command, *arguments],
            cwd=self.root,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def wait_healthy(self, *, attempts: int = 30, delay: float = 1.0) -> None:
        for _ in range(attempts):
            result = self.run(
                "exec",
                "-T",
                "rabbitmq-stream-spike",
                "rabbitmq-diagnostics",
                "-q",
                "check_running",
                check=False,
                timeout=15,
            )
            if result.returncode == 0:
                return
            time.sleep(delay)
        raise RuntimeError("RabbitMQ did not become healthy within the retry budget")

    def clean_start(self) -> None:
        self.run("down", "-v", "--remove-orphans", check=False)
        self.run("up", "-d", "--wait")
        self.wait_healthy()

    def control_application(self, command: str) -> None:
        self.run(
            "exec",
            "-T",
            "rabbitmq-stream-spike",
            "rabbitmqctl",
            command,
        )

    def recover_application(self) -> None:
        self.run(
            "exec",
            "-T",
            "rabbitmq-stream-spike",
            "rabbitmqctl",
            "start_app",
            check=False,
            timeout=30,
        )
        try:
            self.wait_healthy(attempts=10)
        except RuntimeError:
            self.run("restart", "rabbitmq-stream-spike", timeout=60)
            self.run("up", "-d", "--wait")
            self.wait_healthy()


@pytest.fixture(scope="session", autouse=True)
def rabbitmq_compose() -> Iterator[RabbitMqCompose]:
    compose = Path(__file__).parent / "feasibility" / "docker-compose.yml"
    root = Path(__file__).parents[3]
    controller = RabbitMqCompose(
        (
            "uv",
            "run",
            "docker",
            "compose",
            "-f",
            str(compose),
            "-p",
            "kinker-rps0",
        ),
        root,
    )
    if os.environ.get("RPS0_RABBITMQ") != "1":
        yield controller
        return
    controller.clean_start()
    try:
        yield controller
    finally:
        controller.run("down", "-v", "--remove-orphans", check=False)


@pytest.fixture
def destructive_rabbitmq_application(
    rabbitmq_compose: RabbitMqCompose,
) -> Iterator[RabbitMqCompose]:
    yield rabbitmq_compose
    rabbitmq_compose.recover_application()
