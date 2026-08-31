# Native WebSocket Gateway

Run the application with:

```text
uv run tori-py run examples.tori_py.websocket.app:create_application
```

Connect to `ws://127.0.0.1:8000/echo/demo`, send one text frame, and receive
`demo:1:<message>` before the gateway closes the connection.
