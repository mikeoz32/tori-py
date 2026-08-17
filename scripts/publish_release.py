"""Publish a verified release family from local artifacts."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_release import artifact_pairs, verify_digest_manifest  # noqa: E402
from scripts.release_manifest import Distribution, load_manifest  # noqa: E402

REGISTRIES = {
    "testpypi": (
        "https://test.pypi.org/legacy/",
        "https://test.pypi.org/simple/",
    ),
    "pypi": (
        "https://upload.pypi.org/legacy/",
        "https://pypi.org/simple/",
    ),
}
UV_VERSION = "0.11.28"
UV_COMMAND = ["uvx", "--from", f"uv=={UV_VERSION}", "uv"]


def verify_uv_version() -> None:
    output = subprocess.check_output([*UV_COMMAND, "--version"], text=True).strip()
    if output != f"uv {UV_VERSION}" and not output.startswith(f"uv {UV_VERSION} "):
        raise RuntimeError(f"release requires uv {UV_VERSION}, found {output!r}")


def publish_commands(
    dist: Path,
    manifest: tuple[Distribution, ...],
    registry: str,
    *,
    execute: bool,
) -> list[list[str]]:
    publish_url, check_url = REGISTRIES[registry]
    pairs = artifact_pairs(dist, manifest)
    commands: list[list[str]] = []
    for item in manifest:
        wheel, sdist = pairs[item.normalized_name]
        command = [
            *UV_COMMAND,
            "publish",
            "--trusted-publishing",
            "never",
            "--username",
            "__token__",
            "--publish-url",
            publish_url,
            "--check-url",
            check_url,
        ]
        if not execute:
            command.append("--dry-run")
        command.extend((str(wheel.resolve()), str(sdist.resolve())))
        commands.append(command)
    return commands


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", choices=REGISTRIES)
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--digest-manifest", type=Path, default=Path("release-digests.json")
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="upload artifacts; without this flag uv only performs dry runs",
    )
    args = parser.parse_args(argv)

    verify_uv_version()
    manifest = load_manifest()
    verify_digest_manifest(args.dist_dir, args.digest_manifest)
    for command in publish_commands(
        args.dist_dir, manifest, args.registry, execute=args.execute
    ):
        print("+", " ".join(command), flush=True)
        subprocess.run(command, check=True)


if __name__ == "__main__":
    main()
