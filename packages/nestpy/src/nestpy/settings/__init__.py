"""Settings package reserved for the N3 source and decoder implementation."""

import msgspec as _msgspec

from nestpy.core import Codec, SettingsDecoder

_msgspec_module = _msgspec

__all__ = ["Codec", "SettingsDecoder"]
