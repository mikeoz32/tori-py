"""Verify MS11 documentation files and their repository-relative links."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urldefrag

PACKAGE_ROOT = Path(__file__).parents[1]
REQUIRED_DOCS = (
    PACKAGE_ROOT / "docs/USER_GUIDE.md",
    PACKAGE_ROOT / "docs/OPERATIONS.md",
    PACKAGE_ROOT / "../../examples/nestpy/microservices/README.md",
)
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def _check_links(path: Path) -> None:
    for target in MARKDOWN_LINK.findall(path.read_text()):
        target, _ = urldefrag(target)
        if not target or "://" in target:
            continue
        resolved = (path.parent / target).resolve()
        if not resolved.exists():
            raise SystemExit(f"broken documentation link: {path} -> {target}")


def main() -> None:
    for path in REQUIRED_DOCS:
        if not path.is_file():
            raise SystemExit(f"missing MS11 documentation file: {path}")
        _check_links(path)
    _check_links(PACKAGE_ROOT / "README.md")


if __name__ == "__main__":
    main()
