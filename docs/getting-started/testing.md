# Testing

`TestingModule` records provider overrides before it compiles the module graph.
The resulting application uses the normal ASGI path, so tests can verify the
observable HTTP response.

```python
--8<-- "examples/nestpy/getting_started/first_test/test_example.py"
```

Run the test from this repository root:

```text
uv run pytest examples/nestpy/getting_started/first_test/test_example.py
```

The test passes after receiving `{"message":"Hello from test"}` from
`GET /greeting`.
