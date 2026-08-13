# First Test

`TestingModule` records public provider overrides before graph compilation, then
starts a production-equivalent application. The example test replaces the
exported greeting value without modifying the module declaration.

From this repository root, sync the workspace and test dependencies:

```text
uv sync --all-packages --all-groups --extra cli
```

```text
uv run pytest examples/tori_py/getting_started/first_test/test_example.py
```

The test issues `GET /greeting` and verifies the response contains
`Hello from test`. `TestingApplication.http_client()` supplies an
`httpx.AsyncClient` backed by `ASGITransport`; the testing application already
owns startup and shutdown, so HTTPX does not run a second lifespan manager.
