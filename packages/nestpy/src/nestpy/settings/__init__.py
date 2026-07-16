"""Typed settings and bootstrap context for Nestpy."""

import msgspec as _msgspec

from nestpy.core import Codec, SettingsDecoder
from nestpy.settings.context import (
    BootstrapContext,
    current_bootstrap_context,
    use_bootstrap_context,
)
from nestpy.settings.runtime import (
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
