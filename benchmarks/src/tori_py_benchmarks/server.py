"""Start one identically configured Uvicorn process per framework."""

from __future__ import annotations

import http.client
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from types import TracebackType
from typing import NoReturn

from tori_py_benchmarks.registry import Framework

_PROFILE_SHUTDOWN_PATH = "/__tori_py_benchmark_shutdown__"


@dataclass(frozen=True, slots=True)
class HttpResult:
    status: int
    body: bytes
    headers: dict[str, str]


def fetch(port: int, path: str, *, timeout: float = 1.0) -> HttpResult:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return HttpResult(
            response.status,
            response.read(),
            {name.casefold(): value for name, value in response.getheaders()},
        )
    finally:
        connection.close()


class ServerProcess:
    def __init__(
        self,
        framework: Framework,
        *,
        startup_timeout: float = 10.0,
        profile_path: str | None = None,
    ) -> None:
        if startup_timeout <= 0:
            raise ValueError("startup timeout must be positive")
        self.framework = framework
        self.startup_timeout = startup_timeout
        self.profile_path = profile_path
        self.port = 0
        self.startup_seconds = 0.0
        self.rss_bytes: int | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._error_log = tempfile.TemporaryFile()

    def __enter__(self) -> ServerProcess:
        self.port = _available_port()
        command = _server_command(
            self.framework,
            port=self.port,
            profile_path=self.profile_path,
        )
        started = time.perf_counter()
        self._process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=self._error_log,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        deadline = started + self.startup_timeout
        while time.perf_counter() < deadline:
            if self._process.poll() is not None:
                self._raise_startup_error("server exited before readiness")
            try:
                response = fetch(self.port, "/health", timeout=0.2)
            except OSError, http.client.HTTPException:
                time.sleep(0.005)
                continue
            if response.status == 200 and response.body:
                self.startup_seconds = time.perf_counter() - started
                self.rss_bytes = _resident_bytes(self._process.pid)
                return self
            time.sleep(0.005)
        self._raise_startup_error("server did not become ready")

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exception_type, exception, traceback
        process = self._process
        try:
            if process is not None and process.poll() is None:
                if self.profile_path is None:
                    process.terminate()
                else:
                    try:
                        fetch(self.port, _PROFILE_SHUTDOWN_PATH)
                    except OSError, http.client.HTTPException:
                        process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        finally:
            self._process = None
            self._error_log.close()

    def refresh_rss(self) -> int | None:
        process = self._process
        if process is None or process.poll() is not None:
            return None
        self.rss_bytes = _resident_bytes(process.pid)
        return self.rss_bytes

    def _raise_startup_error(self, reason: str) -> NoReturn:
        self._error_log.flush()
        self._error_log.seek(0)
        details = self._error_log.read().decode(errors="replace").strip()
        self.__exit__(None, None, None)
        suffix = f": {details}" if details else ""
        raise RuntimeError(f"{self.framework.name} {reason}{suffix}")


def _server_command(
    framework: Framework,
    *,
    port: int,
    profile_path: str | None = None,
) -> list[str]:
    application = f"{framework.module}:application"
    if profile_path is not None:
        return [
            sys.executable,
            "-m",
            "tori_py_benchmarks.profile_server",
            "--profile",
            profile_path,
            "--application",
            application,
            "--port",
            str(port),
        ]
    return [
        sys.executable,
        "-m",
        "uvicorn",
        application,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--loop",
        "asyncio",
        "--http",
        "httptools",
        "--lifespan",
        "on",
        "--log-level",
        "warning",
        "--no-access-log",
        "--no-server-header",
    ]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _resident_bytes(process_id: int) -> int | None:
    try:
        with open(f"/proc/{process_id}/status", encoding="ascii") as source:
            for line in source:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except IndexError, OSError, ValueError:
        return None
    return None


__all__ = ["HttpResult", "ServerProcess", "fetch"]
