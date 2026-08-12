"""Verify that built distributions contain the typed public package only."""

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
        if not any(
            name.endswith("nestpy_persistent_streams/py.typed") for name in names
        ):
            raise SystemExit(f"{path.name} does not contain py.typed")
        forbidden = ("rabbit", "rstream", "microservices", "sqlalchemy", "starlette")
        package_names = [
            name.lower() for name in names if "nestpy_persistent_streams" in name
        ]
        if any(term in name for term in forbidden for name in package_names):
            raise SystemExit(f"{path.name} contains a forbidden adapter module")


if __name__ == "__main__":
    main()
