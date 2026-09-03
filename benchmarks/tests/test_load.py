from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from tori_py_benchmarks.load import run_load


@contextmanager
def _http_server(status: int, *, delay: float = 0) -> Iterator[int]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            time.sleep(delay)
            body = b"ok"
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_locust_load_records_successful_requests() -> None:
    with _http_server(200) as port:
        result = run_load(port, "/", concurrency=2, duration_seconds=0.2)

    assert result.completed > 0
    assert result.errors == 0
    assert len(result.latencies_ns) == result.completed


def test_locust_load_records_non_200_responses_as_errors() -> None:
    with _http_server(503) as port:
        result = run_load(port, "/", concurrency=1, duration_seconds=0.2)

    assert result.completed > 0
    assert result.errors == result.completed
    assert len(result.latencies_ns) == result.completed


def test_locust_load_stops_without_waiting_for_stalled_responses() -> None:
    with _http_server(200, delay=30) as port:
        started = time.monotonic()
        result = run_load(port, "/", concurrency=1, duration_seconds=0.2)
        elapsed = time.monotonic() - started

    assert result.completed == 0
    assert elapsed < 10


@pytest.mark.parametrize("duration", [float("nan"), float("inf")])
def test_locust_load_rejects_non_finite_duration(duration: float) -> None:
    with pytest.raises(ValueError, match="duration must be finite"):
        run_load(8000, "/", concurrency=1, duration_seconds=duration)
