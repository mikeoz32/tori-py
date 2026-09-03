"""Isolated Locust library runner used by the benchmark orchestrator."""

from __future__ import annotations

import argparse
import json
import os

import gevent
from locust.env import Environment

from tori_py_benchmarks.locustfile import BenchmarkUser, start_requests


def main() -> None:
    arguments = _parse_arguments()
    environment = Environment(user_classes=[BenchmarkUser], host=arguments.host)
    runner = environment.create_local_runner()
    runner.start(arguments.users, spawn_rate=100)
    assert runner.spawning_greenlet is not None
    runner.spawning_greenlet.join()
    environment.stats.reset_all()
    start_requests()
    gevent.sleep(arguments.duration)
    entry = environment.stats.entries[(_path(), "GET")]
    stats = json.dumps(entry.serialize())
    runner.quit()
    print(stats)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--users", required=True, type=int)
    parser.add_argument("--duration", required=True, type=float)
    return parser.parse_args()


def _path() -> str:
    return os.environ["TORI_PY_BENCHMARK_PATH"]


if __name__ == "__main__":
    main()
