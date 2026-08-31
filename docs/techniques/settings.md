# Settings

`SettingsModule` loads ordered configuration sources, merges them, and decodes
the result into one typed model while the application graph is compiled. A
source or decode failure therefore prevents startup before providers, resources,
or lifecycle hooks run.

The minimal application is available in
`examples/tori_py/getting_started/first_settings/app.py`:

```python
--8<-- "examples/tori_py/getting_started/first_settings/app.py"
```

## Registration

`SettingsOptions` has the following inputs:

| Option | Meaning |
| --- | --- |
| `model` | The settings model class. The default codec supports types accepted by `msgspec`, including `msgspec.Struct` and dataclasses. |
| `base_dir` | The only base used to resolve relative source paths. |
| `files` | Ordered TOML, JSON, YAML, or YML files. |
| `dotenv_files` | Ordered dotenv files parsed by ToriPy's narrow parser. |
| `env_prefix` | Case-sensitive prefix removed from process-environment keys. |
| `environment` | Environment mapping to use, or `None` for `os.environ`. Pass `{}` to disable the process environment. |
| `codec` | A custom `Codec`; the default is `MsgspecCodec`. |
| `decoder` | A custom `SettingsDecoder`; the default is `MsgspecSettingsDecoder`. |

`SettingsModule.for_root()` also accepts a dynamic-module `key` and
`global_`. It exports the decoded object under both its model class and
`SETTINGS_TOKEN`; both tokens resolve to the same object. Set `global_=True`
only when every module should see that export. Multiple configured settings
modules should use distinct keys and normal module visibility to avoid an
ambiguous generic `SETTINGS_TOKEN`.

## Source Precedence

Sources have this precedence, from lowest to highest:

```text
model field defaults
explicit files, in declaration order
explicit dotenv files, in declaration order
process or supplied environment
BootstrapContext overrides, normally supplied by tori-py run --set
```

Model defaults are applied by the final decode for fields absent from the merged
mapping. Each later source recursively merges mappings over earlier mappings.
Scalar and sequence values replace the earlier value. They are not appended.

For example, if a first file supplies both `database.host` and
`database.port`, and a later source supplies only `database.host`, the earlier
port remains. If a later source replaces `database` with a scalar, the earlier
mapping is replaced.

There is no automatic profile, filename, or working-directory discovery. Every
file is explicit, and a missing listed source is a bootstrap error.

## Configuration Files

Relative entries in `files` and `dotenv_files` resolve from `base_dir`, not from
the process working directory. Absolute paths remain absolute. File suffix
matching is case-insensitive.

| Suffix | Parser | Additional dependency |
| --- | --- | --- |
| `.toml` | Standard-library `tomllib` | None |
| `.json` | Standard-library `json` | None |
| `.yaml`, `.yml` | `yaml.safe_load` | `tori-py-framework[settings-yaml]` |

Install YAML support explicitly:

```text
uv add 'tori-py-framework[settings-yaml]'
```

Every configuration file must decode to a mapping at its root. Unsupported
suffixes, missing or malformed files, non-mapping roots, and YAML use without
the extra raise `SettingsError` with diagnostic code `settings.source_error`.
YAML uses `safe_load`; selecting YAML does not enable arbitrary Python object
construction.

File mapping keys are passed to the decoder as written. Keep their spelling
aligned with model fields.

## Dotenv Files

Dotenv files are explicit and ordered. The parser supports:

- blank lines and lines whose first non-whitespace character is `#`;
- one `KEY=VALUE` assignment per line;
- whitespace around the key and value;
- single- or double-quoted values with basic Python string escapes;
- `=` characters after the first separator as part of the value;
- final-assignment-wins behavior within one file.

It does not support `export`, interpolation, multiline values, shell expansion,
or inline-comment syntax. An unquoted `#` after `=` is part of the value.
Malformed assignments and unmatched quotes are source errors.

Dotenv names use the same double-underscore model paths as environment names,
but `env_prefix` is deliberately not applied to dotenv files. With
`env_prefix="APP_"`, use these names:

```dotenv
# Explicit dotenv file
DATABASE__HOST=dotenv-host

# Process environment
APP_DATABASE__HOST=environment-host
```

All dotenv values remain text until the final decode.

## Environment And Nested Models

Environment segments are separated with `__`. After removing `env_prefix`,
ToriPy matches each segment case-insensitively to a declared model field and
uses the model's canonical field name:

```text
APP_DATABASE__HOST -> database.host
APP_DATABASE__PORT -> database.port
```

The prefix comparison itself is case-sensitive. Unknown variables and unknown
model paths are ignored rather than rejected. Nested mapping is intended for
named nested model fields; it is not a list-index or arbitrary dictionary-key
syntax. Values remain strings until the codec converts the complete merged
mapping.

Supplying an `environment` mapping is useful for deterministic tests. Omitting
it reads the process environment; supplying `{}` disables that source.

## CLI Overrides

The CLI adds the highest-precedence source with repeated dotted paths:

```text
uv run tori-py run myapp:create_application --set database.host=db.internal --set database.port=6432
```

Paths cannot be empty, values remain text, and the final occurrence of a
duplicate path wins. Use the model's exact dotted field spelling. The CLI does
not validate a path against a model itself; `SettingsModule` validates it when
the deferred module materializes.

Direct ASGI hosting has no implicit CLI source. An exported
`asgi(create_application)` application receives settings from files, dotenv,
the process environment, or configuration explicitly applied by its factory.
`--set` belongs only to `tori-py run`.

## Secrets

Annotate a secret-bearing field with `Secret[T]`:

```python
import msgspec

from tori_py.settings import Secret


class DatabaseSettings(msgspec.Struct):
    password: Secret[str]
```

`secret_paths(Model)` discovers dotted secret paths, including nested model
fields. A `BootstrapContext` or CLI `--set` that targets a secret path, or a
descendant of one, is rejected with `settings.source_error`. The rejected value
is represented as `<redacted>` in the diagnostic and is not echoed in its error
text. Supply secrets through an explicit file, dotenv, or environment instead.

`Secret[T]` is type metadata for redaction policy and CLI rejection. It does not
encrypt the value, fetch it from a secret manager, prevent application code from
logging it, or change the decoded model's runtime representation. Operators must
protect source files and process environments, and application code must not log
the settings object or secret fields.

## Custom Codecs And Decoders

Source selection, parsing, path mapping, precedence, and recursive merging happen
before custom decoding. Extension points affect the final conversion only:

```python
class Codec(Protocol):
    def decode(
        self,
        value: object,
        target: type[object],
        *,
        path: str = "",
    ) -> object: ...

    def encode(self, value: object) -> object: ...


class SettingsDecoder(Protocol):
    def decode(
        self,
        values: Mapping[str, object],
        model: type[object],
        *,
        codec: Codec,
    ) -> object: ...
```

The default `MsgspecSettingsDecoder` makes one call to
`codec.decode(dict(values), model)`. A custom codec can change type conversion
while retaining that flow. A custom decoder receives the complete merged
mapping and selected codec, so it can implement a different model-construction
policy. `Codec.encode()` is part of the shared protocol but is not called by
`load_settings()`.

Raise `SettingsError` when a custom implementation has a safe, specific
diagnostic. Other exceptions from a decoder are wrapped as a value-free
`settings.decode_error` identifying the model. Custom implementations retain
responsibility for avoiding source values and secrets in their own exceptions
and logs.

## Production Guidance

- Anchor `base_dir` to application code or an explicit deployment mount, not the current working directory.
- Keep non-secret defaults in the model or versioned files and inject environment-specific values at deployment time.
- Use environment or read-only mounted files for secrets; do not use CLI arguments, which are commonly visible in process listings and deployment metadata.
- Pass an explicit environment mapping in tests so workstation variables cannot change results.
- Treat ignored unknown environment variables as a reason to validate deployment variable names in CI.
- Fail deployment on any startup settings error rather than serving with an unintended fallback.
