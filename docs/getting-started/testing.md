# Testing

`TestingModule` records provider overrides before it compiles the module graph.
The resulting application uses the normal ASGI path, so tests can verify the
observable HTTP response.

Install the optional HTTP testing client in an application project:

```text
uv add --dev 'tori_py[testing]'
```

`TestingApplication.http_client()` returns an async context manager that yields
an `httpx.AsyncClient` backed by `ASGITransport`. The testing application already
owns startup and shutdown, so the HTTP client does not run another lifespan
manager.

```python
--8<-- "examples/tori_py/getting_started/first_test/test_example.py"
```

Run the test from this repository root:

```text
uv run pytest examples/tori_py/getting_started/first_test/test_example.py
```

The test passes after receiving `{"message":"Hello from test"}` from
`GET /greeting`.
