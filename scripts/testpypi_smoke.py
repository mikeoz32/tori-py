"""Install and smoke-test an exact Tori family release from a package index."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.release_manifest import family_version, load_manifest  # noqa: E402

REGISTRIES = {
    "testpypi": (
        "TestPyPI",
        "https://test.pypi.org/pypi",
        "https://test-files.pythonhosted.org/",
    ),
    "pypi": (
        "PyPI",
        "https://pypi.org/pypi",
        "https://files.pythonhosted.org/",
    ),
}


def _published_files(
    name: str, version: str, api_url: str, registry_label: str
) -> list[dict[str, Any]] | None:
    url = f"{api_url}/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.load(response)
    except urllib.error.HTTPError, urllib.error.URLError:
        return None
    if data["info"]["name"].lower().replace("_", "-") != name.lower().replace("_", "-"):
        raise ValueError(f"{registry_label} returned the wrong project for {name}")
    files = data["urls"]
    if len(files) != 2:
        return None
    return files


def build_testpypi_command(
    wheels: dict[str, tuple[str, str]], names: list[str]
) -> list[str]:
    command = ["uv", "run", "--isolated", "--no-project", "--no-sources"]
    for name in names:
        url, digest = wheels[name]
        command.extend(("--with", f"{url}#sha256={digest}"))
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", choices=REGISTRIES, default="testpypi")
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--delay", type=int, default=30)
    parser.add_argument(
        "--digest-manifest", type=Path, default=Path("release-digests.json")
    )
    args = parser.parse_args()
    registry_label, api_url, file_url_prefix = REGISTRIES[args.registry]
    manifest = load_manifest()
    version = family_version(manifest)
    digest_data = json.loads(args.digest_manifest.read_text(encoding="utf-8"))
    expected_digests = {
        item["filename"]: item["sha256"] for item in digest_data["artifacts"]
    }
    if len(expected_digests) != 24:
        raise ValueError("digest manifest must contain exactly 24 artifacts")
    wheels: dict[str, tuple[str, str]] = {}
    for attempt in range(1, args.attempts + 1):
        published: dict[str, list[dict[str, Any]]] = {}
        for item in manifest:
            files = _published_files(item.name, version, api_url, registry_label)
            if files is not None:
                published[item.name] = files
        wheels = {}
        seen: set[str] = set()
        for name, files in published.items():
            for file in files:
                filename = str(file["filename"])
                url = str(file["url"])
                if not url.startswith(file_url_prefix):
                    raise ValueError(f"{filename} is not sourced from {registry_label}")
                if filename not in expected_digests:
                    raise ValueError(
                        f"unexpected {registry_label} artifact: {filename}"
                    )
                digest = str(file["digests"]["sha256"])
                if digest != expected_digests[filename]:
                    raise ValueError(f"{registry_label} SHA256 mismatch for {filename}")
                seen.add(filename)
                if file["packagetype"] == "bdist_wheel":
                    wheels[name] = (url, digest)
        if published and seen != set(expected_digests):
            missing_files = sorted(set(expected_digests) - seen)
        else:
            missing_files = []
        missing = [item.name for item in manifest if item.name not in wheels]
        if not missing and not missing_files:
            break
        if attempt == args.attempts:
            raise SystemExit(
                f"{registry_label} propagation incomplete: "
                f"projects={missing}, files={missing_files}"
            )
        print(f"{registry_label} attempt {attempt}: waiting for {missing}", flush=True)
        time.sleep(args.delay)

    expected = [
        (item.name, item.version, item.import_names, *wheels[item.name])
        for item in manifest
    ]
    smoke = f"""
import importlib
import importlib.metadata
import json
from pathlib import Path
for distribution, version, imports, artifact_url, artifact_digest in {expected!r}:
    installed = importlib.metadata.distribution(distribution)
    assert installed.version == version
    direct_url = installed.read_text("direct_url.json")
    assert direct_url is not None
    direct = json.loads(direct_url)
    assert direct["url"] == artifact_url
    assert direct["archive_info"]["hash"] == f"sha256={{artifact_digest}}"
    for name in imports:
        module = importlib.import_module(name)
        assert Path(module.__file__).with_name("py.typed").is_file()
"""
    command = build_testpypi_command(wheels, [item.name for item in manifest])
    subprocess.run([*command, "python", "-c", smoke], check=True)
    cli = next(item for item in manifest if item.scripts)
    subprocess.run([*command, next(iter(cli.scripts)), "--help"], check=True)


if __name__ == "__main__":
    main()
