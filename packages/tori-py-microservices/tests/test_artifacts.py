from __future__ import annotations

import tomllib
from pathlib import Path


def test_package_metadata_and_artifacts_are_present() -> None:
    package_root = Path(__file__).parents[1]
    project = tomllib.loads((package_root / "pyproject.toml").read_text())
    assert project["project"]["name"] == "tori-py-microservices"
    assert project["project"]["requires-python"] == ">=3.14,<3.15"
    assert set(project["project"]["dependencies"]) == {
        "msgspec>=0.19.0",
        "tori-py",
    }
    assert project["project"]["optional-dependencies"]["rabbitmq"] == [
        "aio-pika>=10,<11"
    ]
    assert (package_root / "README.md").is_file()
    assert (package_root / "docs/USER_GUIDE.md").is_file()
    assert (package_root / "docs/OPERATIONS.md").is_file()
    assert (package_root / "scripts/verify_artifacts.py").is_file()
    assert (package_root / "scripts/verify_docs.py").is_file()
    assert (package_root / "src/tori_py_microservices/py.typed").is_file()
