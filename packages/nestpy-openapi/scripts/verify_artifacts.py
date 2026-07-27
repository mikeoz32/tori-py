"""Smoke-test nestpy-openapi wheel and source distributions."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SMOKE = r"""
import re
import sys
from importlib.metadata import requires
from pathlib import Path

import nestpy_openapi
from nestpy_openapi import OpenApiInfo, OpenApiOptions, SwaggerUiOptions

expected = {
    "msgspec",
    "nestpy",
    "starlette",
}
actual = set()
for requirement in requires("nestpy-openapi") or ():
    match = re.match(r"[A-Za-z0-9_.-]+", requirement)
    assert match is not None
    actual.add(re.sub(r"[-_.]+", "-", match.group().lower()))
assert actual == expected
assert Path(nestpy_openapi.__file__).with_name("py.typed").is_file()
assert "fastapi" not in sys.modules
assert "pydantic" not in sys.modules
assert OpenApiOptions(
    OpenApiInfo("Artifact API", "0.1.0"),
    swagger_ui=SwaggerUiOptions(parameters={"deepLinking": True}),
)
"""


def _one(dist: Path, pattern: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise SystemExit(
            f"expected one {pattern} artifact in {dist}, found {len(matches)}"
        )
    return matches[0]


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    dist = Path(sys.argv[1]).resolve()
    artifact_sets = (
        (
            _one(dist, "nestpy-0.1.0-*.whl"),
            _one(dist, "nestpy_openapi-*.whl"),
        ),
        (
            _one(dist, "nestpy-0.1.0.tar.gz"),
            _one(dist, "nestpy_openapi-*.tar.gz"),
        ),
    )
    for artifacts in artifact_sets:
        command = ["uv", "run", "--isolated", "--no-project"]
        for artifact in artifacts:
            command.extend(("--with", str(artifact)))
        command.extend(("python", "-c", SMOKE))
        completed = subprocess.run(command, check=False, text=True)
        if completed.returncode:
            raise SystemExit(f"artifact smoke failed: {artifacts[-1].name}")


if __name__ == "__main__":
    main()
