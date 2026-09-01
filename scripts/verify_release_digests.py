"""Verify downloaded release artifacts against the build digest manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_release import artifact_pairs, verify_digest_manifest
from scripts.release_manifest import load_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument(
        "--digest-manifest", type=Path, default=Path("release-digests.json")
    )
    args = parser.parse_args()
    dist = args.dist_dir.resolve()
    pairs = artifact_pairs(dist, load_manifest())
    verify_digest_manifest(
        dist,
        args.digest_manifest.resolve(),
        {artifact.name for pair in pairs.values() for artifact in pair},
    )


if __name__ == "__main__":
    main()
