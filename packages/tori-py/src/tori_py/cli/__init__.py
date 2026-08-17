"""The lazy ``tori-py run`` command."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import inspect
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

from tori_py.settings import BootstrapContext, use_bootstrap_context


def main(argv: Sequence[str] | None = None) -> None:
    """Parse the CLI and delegate serving to the existing ASGI wrapper."""

    parser = _parser()
    arguments = parser.parse_args(argv)
    if arguments.command != "run":
        parser.print_help()
        return
    try:
        factory = _load_factory(arguments.target)
        context = _parse_context(arguments.overrides)
        _serve(factory, context)
    except CLIError as error:
        parser.exit(2, f"tori_py: error: {error}\n")


class CLIError(Exception):
    """Actionable user-facing CLI failure without a traceback."""


def _parser() -> argparse.ArgumentParser:
    try:
        version = importlib.metadata.version("tori_py")
    except importlib.metadata.PackageNotFoundError:
        version = "0.1.0"
    parser = argparse.ArgumentParser(prog="tori_py")
    parser.add_argument("--version", action="version", version=version)
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser("run", help="serve an async application factory")
    run.add_argument("target", help="async factory as module:attribute")
    run.add_argument(
        "--set",
        dest="overrides",
        action="append",
        default=[],
        metavar="PATH=VALUE",
        help="set a non-secret settings path; may be repeated",
    )
    return parser


def _load_factory(target: str) -> Callable[[], object]:
    module_name, separator, attribute_name = target.partition(":")
    if not separator or not module_name or not attribute_name:
        raise CLIError("target must use the module:factory form")
    working_directory = str(Path.cwd())
    if working_directory not in sys.path:
        sys.path.insert(0, working_directory)
    try:
        module = importlib.import_module(module_name)
    except Exception as error:
        raise CLIError(f"could not import module '{module_name}': {error}") from error
    try:
        factory = getattr(module, attribute_name)
    except AttributeError as error:
        raise CLIError(
            f"module '{module_name}' has no factory '{attribute_name}'"
        ) from error
    if not callable(factory):
        raise CLIError(f"factory '{target}' is not callable")
    if not inspect.iscoroutinefunction(factory):
        raise CLIError(f"factory '{target}' must be an async function")
    return factory


def _parse_context(values: Sequence[str]) -> BootstrapContext:
    overrides: dict[str, str] = {}
    for value in values:
        path, separator, setting = value.partition("=")
        if not separator or not path:
            raise CLIError("--set values must use the path=value form")
        overrides[path] = setting
    return BootstrapContext.from_mapping(overrides)


def _serve(factory: Callable[[], object], context: BootstrapContext) -> None:
    try:
        from tori_py.starlette import asgi
    except ImportError as error:
        raise CLIError(
            "The 'tori-py run' command requires the CLI extra.\n"
            "Install it with: uv add 'tori-py-framework[cli]'"
        ) from error

    async def contextual_factory():
        with use_bootstrap_context(context):
            result = factory()
            if inspect.isawaitable(result):
                return await result
            return result

    application = asgi(contextual_factory)
    try:
        uvicorn = cast(Any, importlib.import_module("uvicorn"))
    except ImportError as error:
        raise CLIError(
            "The 'tori-py run' command requires the CLI extra.\n"
            "Install it with: uv add 'tori-py-framework[cli]'"
        ) from error
    uvicorn.run(application, lifespan="on")


__all__ = ["main"]
