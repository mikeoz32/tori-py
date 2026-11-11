from starlette.testclient import TestClient
from tori_py.starlette import asgi

from examples.tori_py.websocket.app import create_application


def test_echo_gateway_keeps_state_per_connection() -> None:
    with TestClient(asgi(create_application)) as client:
        for message in ("hello", "again"):
            with client.websocket_connect("/echo/demo") as socket:
                socket.send_text(message)
                assert socket.receive_text() == f"demo:1:{message}"
