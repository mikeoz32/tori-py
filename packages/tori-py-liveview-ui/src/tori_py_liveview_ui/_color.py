"""Color arithmetic for theme definitions: sRGB, WCAG contrast, and OKLCH."""

from __future__ import annotations

import math
import re

type Rgb = tuple[float, float, float]

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")


def normalize(label: str, value: object, *, opaque: bool) -> str:
    """Return ``#rrggbb`` or ``#rrggbbaa`` in lowercase, or fail."""
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    if _HEX.fullmatch(value) is None:
        raise ValueError(f"{label} must be a #rgb, #rrggbb, or #rrggbbaa color")
    digits = value[1:].lower()
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    if digits.endswith("ff") and len(digits) == 8:
        digits = digits[:6]
    if opaque and len(digits) == 8:
        raise ValueError(f"{label} must be an opaque color")
    return f"#{digits}"


def rgb(color: str) -> Rgb:
    """Return the red, green, and blue channels of a normalized color."""
    return (
        int(color[1:3], 16) / 255,
        int(color[3:5], 16) / 255,
        int(color[5:7], 16) / 255,
    )


def to_hex(color: Rgb) -> str:
    channels = (round(min(1.0, max(0.0, channel)) * 255) for channel in color)
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def with_alpha(color: Rgb, alpha: float) -> str:
    return f"{to_hex(color)}{round(min(1.0, max(0.0, alpha)) * 255):02x}"


def _linear(channel: float) -> float:
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def _encoded(channel: float) -> float:
    if channel <= 0.0031308:
        return channel * 12.92
    return 1.055 * channel ** (1 / 2.4) - 0.055


def luminance(color: Rgb) -> float:
    """Return the WCAG relative luminance."""
    red, green, blue = (_linear(channel) for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: Rgb, second: Rgb) -> float:
    """Return the WCAG contrast ratio of two opaque colors."""
    lighter, darker = sorted((luminance(first), luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def mix(color: Rgb, other: Rgb, share: float) -> Rgb:
    """Mix two colors as ``color-mix(in srgb, color share, other)`` does."""
    return (
        color[0] * share + other[0] * (1 - share),
        color[1] * share + other[1] * (1 - share),
        color[2] * share + other[2] * (1 - share),
    )


# OKLCH, after Björn Ottosson's OKLab: lightness 0..1, chroma, hue in degrees.


def to_oklch(color: Rgb) -> tuple[float, float, float]:
    red, green, blue = (_linear(channel) for channel in color)
    long = math.cbrt(0.4122214708 * red + 0.5363325363 * green + 0.0514459929 * blue)
    medium = math.cbrt(0.2119034982 * red + 0.6806995451 * green + 0.1073969566 * blue)
    short = math.cbrt(0.0883024619 * red + 0.2817188376 * green + 0.6299787005 * blue)
    lightness = 0.2104542553 * long + 0.7936177850 * medium - 0.0040720468 * short
    a = 1.9779984951 * long - 2.4285922050 * medium + 0.4505937099 * short
    b = 0.0259040371 * long + 0.7827717662 * medium - 0.8086757660 * short
    return lightness, math.hypot(a, b), math.degrees(math.atan2(b, a)) % 360


def _oklch_to_linear(lightness: float, chroma: float, hue: float) -> Rgb:
    a = chroma * math.cos(math.radians(hue))
    b = chroma * math.sin(math.radians(hue))
    long = (lightness + 0.3963377774 * a + 0.2158037573 * b) ** 3
    medium = (lightness - 0.1055613458 * a - 0.0638541728 * b) ** 3
    short = (lightness - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (
        4.0767416621 * long - 3.3077115913 * medium + 0.2309699292 * short,
        -1.2684380046 * long + 2.6097574011 * medium - 0.3413193965 * short,
        -0.0041960863 * long - 0.7034186147 * medium + 1.7076147010 * short,
    )


def from_oklch(lightness: float, chroma: float, hue: float) -> Rgb:
    """Return the sRGB color, lowering the chroma until it fits the gamut."""
    lightness = min(1.0, max(0.0, lightness))
    low, high = 0.0, max(0.0, chroma)
    linear = _oklch_to_linear(lightness, high, hue)
    if not _in_gamut(linear):
        for _ in range(24):
            middle = (low + high) / 2
            if _in_gamut(_oklch_to_linear(lightness, middle, hue)):
                low = middle
            else:
                high = middle
        linear = _oklch_to_linear(lightness, low, hue)
    red, green, blue = (_encoded(min(1.0, max(0.0, channel))) for channel in linear)
    return red, green, blue


def _in_gamut(linear: Rgb) -> bool:
    return all(-0.0005 <= channel <= 1.0005 for channel in linear)
