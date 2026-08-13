"""Transport-independent conversion of raw HTTP-bound values."""

import types
from typing import Union, get_args, get_origin

import msgspec

from tori_py.core.protocols import ArgumentMetadata
from tori_py.http.errors import HttpException


class MsgspecValidationPipe:
    """Opt-in raw HTTP value conversion through msgspec."""

    async def transform(self, value: object, metadata: ArgumentMetadata) -> object:
        try:
            return _convert_raw(value, metadata.annotation)
        except (TypeError, ValueError, msgspec.ValidationError) as error:
            raise HttpException(
                400,
                "Validation failed.",
                errors={
                    "parameter": metadata.parameter_name,
                    "source": metadata.binding_kind,
                    "message": str(error),
                },
            ) from error


def _convert_raw(value: object, target: object) -> object:
    try:
        return msgspec.convert(value, type=target)
    except TypeError, ValueError, msgspec.ValidationError:
        pass
    origin = get_origin(target)
    args = get_args(target)
    if origin in {list, tuple, set, frozenset} and isinstance(value, list):
        item_target = args[0] if args else object
        converted = [_convert_raw(item, item_target) for item in value]
        return msgspec.convert(converted, type=target)
    if origin in {types.UnionType, Union}:
        for option in args:
            if option is type(None):
                continue
            try:
                return _convert_raw(value, option)
            except TypeError, ValueError, msgspec.ValidationError:
                continue
    if isinstance(value, str):
        if target is bool:
            normalized = value.casefold()
            if normalized in {"true", "1"}:
                return True
            if normalized in {"false", "0"}:
                return False
        if target in {int, float}:
            return int(value) if target is int else float(value)
    return msgspec.convert(value, type=target)


__all__ = ["MsgspecValidationPipe"]
