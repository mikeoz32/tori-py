"""Small dependency-free HTTP/1.1 load driver for Docker benchmarks."""

from __future__ import annotations

import asyncio
import socket
import time

from tori_py_benchmarks.model import LoadRun

_HEADER_LIMIT = 64 * 1024


def parse_http_response(header: bytes) -> tuple[int, int, bool]:
    if len(header) > _HEADER_LIMIT:
        raise ValueError("HTTP response headers exceed the benchmark limit")
    lines = header.split(b"\r\n")
    status_line = lines[0].split(b" ", 2)
    if len(status_line) < 2 or status_line[0] != b"HTTP/1.1":
        raise ValueError("benchmark requires an HTTP/1.1 response")
    try:
        status = int(status_line[1])
    except ValueError as error:
        raise ValueError("invalid HTTP response status") from error
    headers: dict[bytes, bytes] = {}
    for line in lines[1:]:
        if not line:
            continue
        name, separator, value = line.partition(b":")
        if not separator:
            raise ValueError("invalid HTTP response header")
        headers[name.strip().lower()] = value.strip().lower()
    try:
        content_length = int(headers[b"content-length"])
    except (KeyError, ValueError) as error:
        raise ValueError("benchmark responses require Content-Length") from error
    keep_alive = headers.get(b"connection") != b"close"
    return status, content_length, keep_alive


async def run_load(
    port: int,
    path: str,
    *,
    concurrency: int,
    duration_seconds: float,
) -> LoadRun:
    if concurrency <= 0:
        raise ValueError("concurrency must be positive")
    if duration_seconds <= 0:
        raise ValueError("duration must be positive")
    loop = asyncio.get_running_loop()
    started = time.perf_counter()
    deadline = loop.time() + duration_seconds
    results = await asyncio.gather(
        *(_worker(port, path, deadline) for _ in range(concurrency))
    )
    elapsed = time.perf_counter() - started
    return LoadRun(
        elapsed_seconds=elapsed,
        completed=sum(result[0] for result in results),
        errors=sum(result[1] for result in results),
        latencies_ns=tuple(latency for result in results for latency in result[2]),
    )


async def _worker(
    port: int,
    path: str,
    deadline: float,
) -> tuple[int, int, tuple[int, ...]]:
    request = (
        f"GET {path} HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Accept: */*\r\n"
        "User-Agent: tori-py-benchmark\r\n"
        "Connection: keep-alive\r\n\r\n"
    ).encode("ascii")
    reader: asyncio.StreamReader | None = None
    writer: asyncio.StreamWriter | None = None
    completed = 0
    errors = 0
    latencies: list[int] = []
    try:
        async with asyncio.timeout_at(deadline):
            while True:
                try:
                    if writer is None or writer.is_closing():
                        reader, writer = await asyncio.open_connection(
                            "127.0.0.1", port
                        )
                        connection_socket = writer.get_extra_info("socket")
                        if connection_socket is not None:
                            connection_socket.setsockopt(
                                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
                            )
                    request_started = time.perf_counter_ns()
                    writer.write(request)
                    await writer.drain()
                    assert reader is not None
                    header = await reader.readuntil(b"\r\n\r\n")
                    status, content_length, keep_alive = parse_http_response(header)
                    await reader.readexactly(content_length)
                    if status == 200:
                        completed += 1
                        latencies.append(time.perf_counter_ns() - request_started)
                    else:
                        errors += 1
                    if not keep_alive:
                        _close_writer(writer)
                        reader = None
                        writer = None
                except (
                    OSError,
                    ValueError,
                    asyncio.IncompleteReadError,
                    asyncio.LimitOverrunError,
                ):
                    errors += 1
                    if writer is not None:
                        _close_writer(writer)
                    reader = None
                    writer = None
    except TimeoutError:
        pass
    finally:
        if writer is not None:
            _close_writer(writer)
    return completed, errors, tuple(latencies)


def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()


__all__ = ["parse_http_response", "run_load"]
