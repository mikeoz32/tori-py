"""The reference specification intentionally uses native async fixtures."""

from __future__ import annotations

from _pytest.config import Config


def pytest_configure(config: Config) -> None:
    # pytest-asyncio 1.x defaults to strict mode; these fixtures are part of the
    # executable specification, so opt this directory into its compatibility mode.
    config.option.asyncio_mode = "auto"
