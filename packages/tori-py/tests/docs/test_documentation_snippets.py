"""Execute the Python blocks of the user documentation.

Each page runs in its own interpreter. Its blocks execute in order in one
module namespace, so a block may use names that earlier blocks on the same page
define. Top-level ``await`` runs on one event loop per page.

An HTML comment on the nearest non-blank line before a block changes how it
runs:

- ``<!-- docs-test: skip -->`` marks a deliberate fragment, such as a method
  shown without its class, a placeholder import, or a server start.
- ``<!-- docs-test: raises Name -->`` requires the block to raise an exception
  whose class, or one of its base classes, is named ``Name``.

Blocks that include an example file with ``--8<--`` are not executed here; the
example's own tests cover them.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import os
import re
import subprocess
import sys
import traceback
import types
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
DOCS = ROOT / "docs"
EXCLUDED = (DOCS / "reference" / "generated",)
FENCE = re.compile(r"^```python[^\n]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
INCLUDE = re.compile(r'--8<--\s+"[^"]+"')
MARKER = re.compile(r"<!--\s*docs-test:\s*(.*?)\s*-->")
DIRECTIVE = re.compile(r"skip|raises ([A-Za-z_][A-Za-z0-9_]*)")
PAGE_TIMEOUT = 180.0
BLOCK_TIMEOUT = 30.0
MODULE_NAME = "docs_snippet"


@dataclass(frozen=True, slots=True)
class Block:
    line: int
    source: str
    skip: bool
    raises: str | None


def _pages() -> list[Path]:
    return sorted(
        page
        for page in DOCS.rglob("*.md")
        if not any(page.is_relative_to(excluded) for excluded in EXCLUDED)
    )


def _location(page: Path, line: int) -> str:
    return f"{page.relative_to(ROOT).as_posix()}:{line}"


def _blocks(page: Path) -> list[Block]:
    text = page.read_text(encoding="utf-8")
    blocks: list[Block] = []
    for match in FENCE.finditer(text):
        source = match.group(1)
        if INCLUDE.fullmatch(source.strip()):
            continue
        line = text.count("\n", 0, match.start()) + 1
        previous = text[: match.start()].rstrip().rpartition("\n")[2].strip()
        marker = MARKER.fullmatch(previous)
        # An invalid marker leaves the block unmarked; the marker test reports it.
        directive = None if marker is None else DIRECTIVE.fullmatch(marker.group(1))
        blocks.append(
            Block(
                line=line,
                source=source,
                skip=directive is not None and directive.group(0) == "skip",
                raises=None if directive is None else directive.group(1),
            )
        )
    return blocks


def _raised_name(error: BaseException, name: str) -> bool:
    return any(cls.__name__ == name for cls in type(error).__mro__)


def _run_block(
    block: Block,
    page: Path,
    namespace: dict[str, object],
    loop: asyncio.AbstractEventLoop,
) -> None:
    # Leading newlines keep traceback line numbers equal to the page's lines.
    code = compile(
        "\n" * block.line + block.source,
        str(page),
        "exec",
        flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT,
        dont_inherit=True,
    )
    if code.co_flags & inspect.CO_COROUTINE:
        loop.run_until_complete(asyncio.wait_for(eval(code, namespace), BLOCK_TIMEOUT))
    else:
        exec(code, namespace)


def _close(loop: asyncio.AbstractEventLoop) -> None:
    pending = asyncio.all_tasks(loop)
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
    loop.run_until_complete(loop.shutdown_asyncgens())
    loop.close()


def _run_page(page: Path) -> int:
    module = types.ModuleType(MODULE_NAME)
    module.__file__ = str(page)
    sys.modules[MODULE_NAME] = module
    loop = asyncio.new_event_loop()
    try:
        for block in _blocks(page):
            if block.skip:
                continue
            location = _location(page, block.line)
            try:
                _run_block(block, page, module.__dict__, loop)
            except Exception as error:
                if block.raises is not None and _raised_name(error, block.raises):
                    continue
                print(f"{location}: block raised:", file=sys.stderr)
                traceback.print_exception(error)
                return 1
            if block.raises is not None:
                print(
                    f"{location}: expected {block.raises}, but nothing was raised",
                    file=sys.stderr,
                )
                return 1
    finally:
        _close(loop)
        sys.modules.pop(MODULE_NAME, None)
    return 0


PAGES = tuple(
    page for page in _pages() if any(not block.skip for block in _blocks(page))
)


@pytest.mark.parametrize(
    "page", PAGES, ids=[page.relative_to(DOCS).as_posix() for page in PAGES]
)
def test_page_python_blocks_run(page: Path, tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, __file__, str(page)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=PAGE_TIMEOUT,
        env={**os.environ, "PYTHONUTF8": "1"},
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_markers_precede_python_blocks() -> None:
    problems: list[str] = []
    for page in _pages():
        lines = page.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            marker = MARKER.search(line)
            if marker is None:
                continue
            location = _location(page, index + 1)
            if (
                MARKER.fullmatch(line.strip()) is None
                or DIRECTIVE.fullmatch(marker.group(1)) is None
            ):
                problems.append(f"{location}: invalid marker {line.strip()!r}")
                continue
            following = next((text for text in lines[index + 1 :] if text.strip()), "")
            if not following.startswith("```python"):
                problems.append(f"{location}: marker does not precede a python block")
    assert not problems, "\n".join(problems)


if __name__ == "__main__":
    raise SystemExit(_run_page(Path(sys.argv[1])))
