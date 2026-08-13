# Phase N3: Settings, Logging, and Testing

## Purpose

Add cross-cutting framework modules that rely on the stable N2 container:
typed settings, structured logging, bootstrap context, and testing overrides.
No HTTP driver is implemented in this phase.

## Entry Criteria

- N2 lifecycle/resource contracts pass.
- Dynamic module materialization and public exports are stable.
- Msgspec is available as a required ToriPy dependency.

## Bootstrap Context

Define immutable `BootstrapContext` with non-secret CLI overrides. A private
context variable exposes it only while an exported application factory and
deferred modules materialize. The context variable is reset in `finally`.

External hosting normally creates an empty bootstrap context. The CLI integration
that fills it is implemented in N6.

## Settings Options

`SettingsOptions` contains:

- model type;
- explicit `base_dir`;
- ordered config files;
- ordered dotenv files;
- environment prefix/options;
- global-module opt-in through `SettingsModule.for_root(..., global_=...)`.

Relative paths resolve only from `base_dir`, never the current process directory.

## Source Precedence

Lowest to highest:

```text
model defaults
explicit TOML/JSON/YAML files in declaration order
explicit dotenv files in declaration order
process environment
non-secret BootstrapContext overrides
```

Mapping values merge recursively. Scalars and sequences replace earlier values.

Parsers:

- TOML: `tomllib`;
- JSON: standard `json`;
- YAML: lazy PyYAML import and `yaml.safe_load` only;
- dotenv: narrow in-package parser supporting `KEY=VALUE`, comments, and basic
  single/double quotes, with no interpolation or multiline syntax.

All file roots must be mappings. Selecting YAML without the extra is a typed,
actionable settings error.

## Environment and CLI Mapping

Environment mapping uses explicit prefix plus `__` nesting. Only paths present
in the settings model are considered; unrelated variables are ignored. Source
values remain textual until msgspec conversion.

CLI override paths use dotted notation. Duplicate paths use the final value.
Overrides targeting `Secret[T]` paths MUST be rejected. Secrets are supplied
through files, dotenv, or environment only.

## Decode and Redaction

Merge sources into a mapping, then convert once through msgspec to the settings
model. Decode failure prevents application startup.

N3 implements the `Codec` and `SettingsDecoder` protocols declared in N0 with a
msgspec-backed default. SettingsModule depends on the protocol, not direct
ad-hoc msgspec calls, so later codecs can replace it without changing source
loading/merge behavior.

`Secret[T]` metadata records redacted model paths. Logs/errors MUST NOT include
raw source values at or below those paths. Diagnostics include source identity,
model path, expected type, and redacted input marker.

`SettingsModule` exports both a generic settings token and an alias under the
model class token.

## Logging

Implement the injectable `Logger` protocol declared in N0 with a default Python
logging provider.
The default is supplied by an internal opt-in global framework module and
resolves through normal provider visibility, not a container fallback.

Structured fields include application, module, provider, route, scope, request
ID, and resource state where available. User fields MUST NOT overwrite reserved
framework fields.

Request ID HTTP behavior belongs to N4; N3 defines correlation storage and
logger-binding primitives only.

## Testing Module

`TestingModule.create(root)` returns a mutable builder without materializing the
module graph.

Supported pre-compilation operations:

- replace a deferred module descriptor before materialization;
- override an exported provider token in a specified static module;
- override an exported provider token in a specified dynamic `(class, key)`;
- override a global exported token;
- use value/class/factory/alias declarations.

Private providers are not externally overrideable. Provider overrides apply
after module materialization/shape validation but before visibility,
dependencies, aliases, cycles, and scopes are finalized. Module overrides apply
before materialization.

`compile()` seals the builder, compiles the graph, starts the application, and
returns `TestingApplication`. Late overrides are errors.

Testing application exposes:

- documented container resolution by token plus module identity;
- async `close()` using production shutdown behavior;
- no separate cleanup implementation.

ASGI testing support is added in N4 without changing override semantics.

## Explicit Non-Goals

N3 MUST NOT:

- implement CLI argument parsing or start Uvicorn;
- implement Starlette request IDs;
- create controllers/routes;
- implement HTTP validation pipes;
- permit private-provider override shortcuts.

## Tests

Tests MUST cover:

1. source precedence;
2. explicit base-directory resolution;
3. ordered deep merge and replacement;
4. TOML/JSON parsing;
5. safe YAML and missing-extra error;
6. dotenv accepted/rejected grammar;
7. environment prefix/nesting/unrelated variables;
8. msgspec settings conversion;
9. SettingsModule resolves and invokes the N0 `SettingsDecoder` protocol;
10. alternate test decoder can replace the msgspec implementation;
11. secret path discovery and redaction;
12. secret bootstrap override rejection;
13. settings dynamic/global exports;
14. bootstrap context isolation/reset;
15. logger reserved fields;
16. default logger visibility and module/provider/scope correlation fields;
17. module override before materialization;
18. public provider overrides by static/dynamic module identity;
19. private override rejection;
20. override syntax revalidation;
21. compile seals builder;
22. testing startup/close uses production lifecycle;
23. settings source failures occur before startup and prove that no resources
    or hooks ran while BootstrapContext was still reset.

## Exit Criteria

N3 is complete when settings load deterministically and securely, logs expose
framework context without secrets, and tests can replace public graph components
before compilation while using the production container/lifecycle.
