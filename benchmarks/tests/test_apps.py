from __future__ import annotations

import json

import pytest

from tori_py_benchmarks.registry import FRAMEWORKS, SCENARIOS, Framework
from tori_py_benchmarks.server import ServerProcess, _server_command, fetch


@pytest.mark.parametrize("framework", FRAMEWORKS, ids=lambda item: item.name)
def test_framework_apps_serve_the_same_observable_contract(
    framework: Framework,
) -> None:
    with ServerProcess(framework, startup_timeout=15.0) as server:
        plaintext = fetch(server.port, "/plaintext")
        json_response = fetch(server.port, "/json")
        singleton_response = fetch(server.port, "/singleton")
        inject_response = fetch(server.port, "/inject")

    assert plaintext.status == 200
    assert plaintext.body == SCENARIOS["plaintext"]
    assert json.loads(json_response.body) == SCENARIOS["json"]
    assert json.loads(singleton_response.body) == SCENARIOS["singleton"]
    assert json.loads(inject_response.body) == SCENARIOS["inject"]


def test_profiled_server_uses_controlled_profile_runner() -> None:
    command = _server_command(
        FRAMEWORKS[-1],
        port=8123,
        profile_path="/results/tori.pstats",
    )

    assert command[1:6] == [
        "-m",
        "tori_py_benchmarks.profile_server",
        "--profile",
        "/results/tori.pstats",
        "--application",
    ]
    assert command[6:8] == [
        "tori_py_benchmarks.apps.tori_py_asgi_app:application",
        "--port",
    ]


def test_profiled_server_writes_stats_on_shutdown(tmp_path) -> None:
    profile_path = tmp_path / "tori.pstats"

    with ServerProcess(
        FRAMEWORKS[-1],
        startup_timeout=15.0,
        profile_path=str(profile_path),
    ) as server:
        assert fetch(server.port, "/plaintext").status == 200

    assert profile_path.stat().st_size > 0
