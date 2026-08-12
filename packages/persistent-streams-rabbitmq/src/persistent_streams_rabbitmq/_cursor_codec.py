from __future__ import annotations

from persistent_streams import CursorKind, ResumeCursor

MAX_CURSOR_OFFSET = (1 << 63) - 1
MAX_BROKER_CURSOR = (1 << 64) - 1


def encode_cursor(cursor: ResumeCursor) -> int:
    if cursor.offset > MAX_CURSOR_OFFSET:
        raise OverflowError(f"cursor offset exceeds {MAX_CURSOR_OFFSET}")
    kind_bit = 0 if cursor.kind is CursorKind.INITIALIZED else 1
    return (cursor.offset << 1) | kind_bit


def decode_cursor(value: int) -> ResumeCursor:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("broker cursor must be an integer")
    if value < 0 or value > MAX_BROKER_CURSOR:
        raise OverflowError("broker cursor is outside uint64")
    offset = value >> 1
    if value & 1:
        return ResumeCursor.last_successful(offset)
    return ResumeCursor.initialized(offset)
