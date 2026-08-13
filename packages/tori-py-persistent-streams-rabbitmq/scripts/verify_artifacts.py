"""Verify typed RabbitMQ adapter wheel and source artifacts."""

from __future__ import annotations

import sys
import tarfile
import zipfile
from pathlib import Path


def main() -> None:
    paths = tuple(Path(value) for value in sys.argv[1:])
    if not paths:
        raise SystemExit("pass wheel and sdist paths")
    for path in paths:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(path) as archive:
                names = archive.getnames()
        required = (
            "tori_py_persistent_streams_rabbitmq/__init__.py",
            "tori_py_persistent_streams_rabbitmq/py.typed",
            "tori_py_persistent_streams_rabbitmq/_rstream_compat.py",
            "tori_py_persistent_streams_rabbitmq/lease.py",
            "tori_py_persistent_streams_rabbitmq/log.py",
            "tori_py_persistent_streams_rabbitmq/tori_py.py",
            "tori_py_persistent_streams_rabbitmq/publishing.py",
            "tori_py_persistent_streams_rabbitmq/reading.py",
            "tori_py_persistent_streams_rabbitmq/topology.py",
        )
        if any(not any(name.endswith(item) for name in names) for item in required):
            raise SystemExit(f"{path.name} omits required adapter files")
        if path.suffix == ".whl" and any("/tests/" in name for name in names):
            raise SystemExit(f"{path.name} contains tests")


if __name__ == "__main__":
    main()
