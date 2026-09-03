from __future__ import annotations

import os

from gevent.event import Event
from locust import FastHttpUser, task

_PATH = os.environ["TORI_PY_BENCHMARK_PATH"]
_START = Event()


def start_requests() -> None:
    _START.set()


class BenchmarkUser(FastHttpUser):
    @task
    def benchmark(self) -> None:
        _START.wait()
        with self.client.get(_PATH, name=_PATH, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"unexpected HTTP status {response.status_code}")
