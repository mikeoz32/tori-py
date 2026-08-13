"""Delegate artifact verification to the repository family verifier."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_artifacts.py DIST_DIR")
    root = Path(__file__).resolve().parents[3]
    sys.argv = ["build_release.py", "--dist-dir", sys.argv[1], "--verify-only"]
    runpy.run_path(str(root / "scripts" / "build_release.py"), run_name="__main__")


if __name__ == "__main__":
    main()
