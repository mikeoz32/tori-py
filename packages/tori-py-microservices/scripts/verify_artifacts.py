"""Delegate artifact checks and optional broker smoke to the family verifier."""

import argparse
import runpy
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        usage="verify_artifacts.py DIST_DIR [RABBITMQ_URL]"
    )
    parser.add_argument("dist_dir")
    parser.add_argument("rabbitmq_url", nargs="?")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[3]
    forwarded = [
        "build_release.py",
        "--dist-dir",
        args.dist_dir,
        "--verify-only",
    ]
    if args.rabbitmq_url:
        forwarded.extend(("--rabbitmq-url", args.rabbitmq_url))
    sys.argv = forwarded
    runpy.run_path(str(root / "scripts" / "build_release.py"), run_name="__main__")


if __name__ == "__main__":
    main()
