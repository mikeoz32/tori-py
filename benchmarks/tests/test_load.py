from __future__ import annotations

import asyncio

from tori_py_benchmarks.load import parse_http_response, run_load


def test_http_response_parser_reads_content_length_and_keep_alive() -> None:
    status, length, keep_alive = parse_http_response(
        b"HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n"
        b"content-length: 17\r\nconnection: keep-alive\r\n\r\n"
    )

    assert status == 200
    assert length == 17
    assert keep_alive is True


def test_http_response_parser_detects_connection_close() -> None:
    status, length, keep_alive = parse_http_response(
        b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n"
        b"Connection: close\r\n\r\n"
    )

    assert status == 503
    assert length == 0
    assert keep_alive is False


def test_load_counts_malformed_responses_instead_of_aborting() -> None:
    async def exercise() -> None:
        async def malformed_response(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            del reader
            writer.write(b"not-http\r\n\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(malformed_response, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        try:
            result = await run_load(port, "/", concurrency=1, duration_seconds=0.02)
        finally:
            server.close()
            await server.wait_closed()
        assert result.completed == 0
        assert result.errors > 0

    asyncio.run(exercise())


def test_load_stops_at_the_deadline_when_a_response_stalls() -> None:
    async def exercise() -> float:
        handlers: set[asyncio.Task[None]] = set()

        async def stalled_response(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            del reader
            task = asyncio.current_task()
            assert task is not None
            handlers.add(task)
            try:
                await asyncio.sleep(10)
            finally:
                writer.close()
                handlers.discard(task)

        server = await asyncio.start_server(stalled_response, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        loop = asyncio.get_running_loop()
        started = loop.time()
        try:
            result = await run_load(port, "/", concurrency=1, duration_seconds=0.02)
            elapsed = loop.time() - started
        finally:
            for handler in handlers:
                handler.cancel()
            await asyncio.gather(*handlers, return_exceptions=True)
            server.close()
            await server.wait_closed()
        assert result.completed == 0
        return elapsed

    assert asyncio.run(exercise()) < 0.5
