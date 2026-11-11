"""Typed settings for the Task API database."""

from pathlib import Path

import msgspec
from tori_py.settings import SettingsModule, SettingsOptions


class DatabaseSettings(msgspec.Struct, frozen=True):
    url: str = "sqlite+aiosqlite:///tasks.db"


class TaskApiSettings(msgspec.Struct, frozen=True):
    database: DatabaseSettings = msgspec.field(default_factory=DatabaseSettings)


SETTINGS_OPTIONS = SettingsOptions(
    model=TaskApiSettings,
    base_dir=Path(__file__).parent,
    env_prefix="TASK_API_",
)

settings_module = SettingsModule.for_root(SETTINGS_OPTIONS)
