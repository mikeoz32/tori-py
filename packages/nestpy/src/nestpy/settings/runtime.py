"""Settings sources, decoding, secret metadata, and SettingsModule."""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, TypeVar, cast, get_args, get_origin, get_type_hints

import msgspec

from nestpy.core.errors import SettingsError
from nestpy.core.modules import DeferredModule, ModuleSpec
from nestpy.core.protocols import Codec, SettingsDecoder
from nestpy.core.providers import AliasProvider, ValueProvider
from nestpy.settings.context import current_bootstrap_context

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SecretMarker:
    """Type metadata marker used only for redaction and CLI policy."""


type Secret[T] = Annotated[T, SecretMarker()]

SETTINGS_TOKEN = "nestpy.settings"


@dataclass(frozen=True, slots=True)
class SettingsOptions:
    """Explicit settings model and source configuration."""

    model: type[object]
    base_dir: Path
    files: tuple[str | Path, ...] = ()
    dotenv_files: tuple[str | Path, ...] = ()
    env_prefix: str = ""
    environment: Mapping[str, str] | None = None
    codec: Codec | None = None
    decoder: SettingsDecoder | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, type):
            raise SettingsError(
                "settings model must be a class",
                code="settings.source_error",
            )
        object.__setattr__(self, "base_dir", Path(self.base_dir))
        object.__setattr__(self, "files", tuple(self.files))
        object.__setattr__(self, "dotenv_files", tuple(self.dotenv_files))
        if not isinstance(self.env_prefix, str):
            raise SettingsError(
                "settings environment prefix must be text",
                code="settings.source_error",
            )


class MsgspecCodec:
    """Default codec backed by msgspec conversion and builtins encoding."""

    def decode(
        self,
        value: object,
        target: type[object],
        *,
        path: str = "",
    ) -> object:
        try:
            return msgspec.convert(value, type=target, strict=False)
        except Exception as error:
            raise SettingsError(
                "settings value failed type conversion",
                code="settings.decode_error",
                details={"path": path or "<root>", "expected": target.__qualname__},
            ) from error

    def encode(self, value: object) -> object:
        return msgspec.to_builtins(value)


class MsgspecSettingsDecoder:
    """Default SettingsDecoder implementation using the injected Codec."""

    def decode(
        self,
        values: Mapping[str, object],
        model: type[object],
        *,
        codec: Codec,
    ) -> object:
        return codec.decode(dict(values), model)


def secret_paths(model: type[object]) -> tuple[str, ...]:
    """Return dotted model paths annotated with ``Secret`` metadata."""

    result: list[str] = []

    def walk(target: object, prefix: str) -> None:
        try:
            hints = get_type_hints(target, include_extras=True)  # type: ignore[arg-type]
        except NameError, TypeError, ValueError:
            hints = getattr(target, "__annotations__", {})
        for name, annotation in hints.items():
            path = f"{prefix}.{name}" if prefix else name
            base, secret = _unwrap_secret(annotation)
            if secret:
                result.append(path)
            nested = base if isinstance(base, type) else None
            if nested is not None and _has_model_fields(nested):
                walk(nested, path)

    walk(model, "")
    return tuple(result)


class SettingsModule:
    """Dynamic module that loads one typed settings model."""

    @classmethod
    def for_root(
        cls,
        options: SettingsOptions,
        *,
        key: str = "default",
        global_: bool = False,
    ) -> DeferredModule:
        return DeferredModule(
            cls,
            key,
            lambda: cls._materialize(options, global_=global_),
        )

    @classmethod
    def _materialize(cls, options: SettingsOptions, *, global_: bool) -> ModuleSpec:
        values = load_settings(options)
        return ModuleSpec(
            providers=[
                ValueProvider(SETTINGS_TOKEN, values),
                AliasProvider(options.model, SETTINGS_TOKEN),
            ],
            exports=[SETTINGS_TOKEN, options.model],
            global_=global_,
        )


def load_settings(options: SettingsOptions) -> object:
    """Load, merge, and decode settings without exposing source values."""

    merged: dict[str, object] = {}
    for file_path in options.files:
        source_path = _resolve_path(options.base_dir, file_path)
        _merge_into(merged, _read_file(source_path))
    for dotenv_path in options.dotenv_files:
        source_path = _resolve_path(options.base_dir, dotenv_path)
        _merge_into(
            merged,
            _environment_mapping(
                options.model,
                _read_dotenv(source_path),
                prefix="",
            ),
        )
    environment = options.environment if options.environment is not None else os.environ
    _merge_into(
        merged,
        _environment_mapping(options.model, environment, prefix=options.env_prefix),
    )
    context = current_bootstrap_context()
    protected = set(secret_paths(options.model))
    for path, value in context.overrides:
        if path in protected or any(
            path.startswith(f"{secret}.") for secret in protected
        ):
            raise SettingsError(
                "bootstrap override targets a secret settings path",
                code="settings.source_error",
                details={"path": path, "value": "<redacted>"},
            )
        if not _path_exists(options.model, path.split(".")):
            raise SettingsError(
                "bootstrap override targets an unknown settings path",
                code="settings.source_error",
                details={"path": path},
            )
        _set_nested(merged, path.split("."), value)
    codec = options.codec or MsgspecCodec()
    decoder = options.decoder or MsgspecSettingsDecoder()
    try:
        return decoder.decode(merged, options.model, codec=codec)
    except SettingsError:
        raise
    except Exception as error:
        raise SettingsError(
            "settings model could not be decoded",
            code="settings.decode_error",
            details={"model": options.model.__qualname__},
        ) from error


def _resolve_path(base_dir: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _read_file(path: Path) -> dict[str, object]:
    try:
        suffix = path.suffix.casefold()
        raw = path.read_bytes()
        if suffix == ".toml":
            value = tomllib.loads(raw.decode())
        elif suffix == ".json":
            value = json.loads(raw)
        elif suffix in {".yaml", ".yml"}:
            try:
                yaml = cast(Any, importlib.import_module("yaml"))
            except ImportError as error:
                raise SettingsError(
                    "YAML settings require the settings-yaml extra",
                    code="settings.source_error",
                ) from error
            value = yaml.safe_load(raw)
        else:
            raise SettingsError(
                f"unsupported settings file suffix: {suffix}",
                code="settings.source_error",
            )
    except SettingsError:
        raise
    except Exception as error:
        raise SettingsError(
            "settings source could not be read",
            code="settings.source_error",
            details={"source": str(path)},
        ) from error
    if not isinstance(value, Mapping):
        raise SettingsError(
            "settings file root must be a mapping",
            code="settings.source_error",
            details={"source": str(path)},
        )
    return {str(key): item for key, item in value.items()}


def _read_dotenv(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text().splitlines()
    except Exception as error:
        raise SettingsError(
            "dotenv source could not be read",
            code="settings.source_error",
            details={"source": str(path)},
        ) from error
    result: dict[str, str] = {}
    for index, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            raise SettingsError(
                "invalid dotenv assignment",
                code="settings.source_error",
                details={"source": str(path), "line": index},
            )
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or "\n" in value:
            raise SettingsError(
                "invalid dotenv assignment",
                code="settings.source_error",
                details={"source": str(path), "line": index},
            )
        if value[:1] in {"'", '"'}:
            if len(value) < 2 or value[-1] != value[0]:
                raise SettingsError(
                    "invalid dotenv quoting",
                    code="settings.source_error",
                    details={"source": str(path), "line": index},
                )
            try:
                value = ast.literal_eval(value)
            except (SyntaxError, ValueError) as error:
                raise SettingsError(
                    "invalid dotenv quoting",
                    code="settings.source_error",
                    details={"source": str(path), "line": index},
                ) from error
        result[key] = value
    return result


def _environment_mapping(
    model: type[object],
    values: Mapping[str, str],
    *,
    prefix: str,
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in values.items():
        if prefix and not key.startswith(prefix):
            continue
        path = key[len(prefix) :].split("__") if prefix else key.split("__")
        resolved = _canonical_path(model, path)
        if resolved is not None:
            _set_nested(result, resolved, value)
    return result


def _canonical_path(model: type[object], parts: list[str]) -> list[str] | None:
    current: object = model
    canonical: list[str] = []
    for part in parts:
        fields = _model_field_names(current)
        match = next(
            (name for name in fields if name.casefold() == part.casefold()), None
        )
        if match is None:
            return None
        canonical.append(match)
        annotation = _model_hints(current).get(match)
        current, _ = _unwrap_secret(annotation)
        origin = get_origin(current)
        if origin is not None:
            args = [arg for arg in get_args(current) if arg is not type(None)]
            current = args[0] if len(args) == 1 else current
    return canonical


def _path_exists(model: type[object], parts: list[str]) -> bool:
    return _canonical_path(model, parts) is not None


def _set_nested(target: dict[str, object], path: list[str], value: object) -> None:
    current = target
    for part in path[:-1]:
        child_value = current.get(part)
        if isinstance(child_value, dict):
            child = cast(dict[str, object], child_value)
        else:
            child = {}
            current[part] = child
        current = child
    current[path[-1]] = value


def _merge_into(target: dict[str, object], source: Mapping[str, object]) -> None:
    for key, value in source.items():
        existing = target.get(key)
        if isinstance(value, Mapping) and isinstance(existing, dict):
            existing = cast(dict[str, object], existing)
            nested = {
                str(nested_key): nested_value
                for nested_key, nested_value in value.items()
            }
            _merge_into(existing, nested)
        elif isinstance(value, Mapping):
            target[key] = {
                str(nested_key): nested_value
                for nested_key, nested_value in value.items()
            }
        else:
            target[key] = value


def _model_hints(model: object) -> dict[str, object]:
    try:
        return dict(get_type_hints(model, include_extras=True))  # type: ignore[arg-type]
    except NameError, TypeError, ValueError:
        return dict(getattr(model, "__annotations__", {}))


def _model_field_names(model: object) -> tuple[str, ...]:
    if dataclasses.is_dataclass(model):
        return tuple(field.name for field in dataclasses.fields(model))
    fields = getattr(model, "__struct_fields__", ())
    if fields:
        return tuple(fields)
    return tuple(_model_hints(model))


def _has_model_fields(model: type[object]) -> bool:
    return bool(_model_field_names(model))


def _unwrap_secret(annotation: object) -> tuple[object, bool]:
    if get_origin(annotation) is Secret:
        args = get_args(annotation)
        return (args[0] if args else object), True
    if get_origin(annotation) is Annotated:
        args = get_args(annotation)
        base, secret = _unwrap_secret(args[0])
        return base, secret or any(
            isinstance(value, SecretMarker) for value in args[1:]
        )
    return annotation, False


__all__ = [
    "SETTINGS_TOKEN",
    "MsgspecCodec",
    "MsgspecSettingsDecoder",
    "Secret",
    "SecretMarker",
    "SettingsModule",
    "SettingsOptions",
    "load_settings",
    "secret_paths",
]
