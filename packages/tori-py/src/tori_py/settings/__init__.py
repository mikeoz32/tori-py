"""Typed settings and bootstrap context for ToriPy."""

import msgspec as _msgspec

from tori_py.core import Codec, SettingsDecoder
from tori_py.settings.context import (
    BootstrapContext,
    current_bootstrap_context,
    use_bootstrap_context,
)
from tori_py.settings.runtime import (
    SETTINGS_TOKEN,
    MsgspecCodec,
    MsgspecSettingsDecoder,
    Secret,
    SecretMarker,
    SettingsModule,
    SettingsOptions,
    load_settings,
    secret_paths,
)

_msgspec_module = _msgspec

__all__ = [
    "BootstrapContext",
    "Codec",
    "SETTINGS_TOKEN",
    "MsgspecCodec",
    "MsgspecSettingsDecoder",
    "Secret",
    "SecretMarker",
    "SettingsDecoder",
    "SettingsModule",
    "SettingsOptions",
    "current_bootstrap_context",
    "load_settings",
    "secret_paths",
    "use_bootstrap_context",
]
