"""Delegate to the canonical family artifact verifier."""

import runpy
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[3]
sys.argv = ["build_release.py", "--dist-dir", *sys.argv[1:], "--verify-only"]
runpy.run_path(str(root / "scripts" / "build_release.py"), run_name="__main__")
