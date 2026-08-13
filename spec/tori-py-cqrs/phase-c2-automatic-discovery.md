# C2: Automatic Handler Discovery

## Purpose

Register CQRS handlers from classes already declared as ToriPy providers, so an
application does not repeat the same handler in `CqrsModule.for_root()`.

## Contract

- `CqrsModule.for_root()` discovers decorated provider classes by default.
- ToriPy-native handler decorators compose `tori-py-cqrs-core` metadata with direct
  injectable metadata and accept `scope` plus `manage` settings.
- Decorated handlers are still registered explicitly by listing their classes in
  module `providers`; decorators never auto-register classes.
- `handlers` is optional and remains the explicit escape hatch.
- Discovery uses public ToriPy `DiscoveryService` and public
  `tori_py_cqrs_core.get_handler_metadata()`; neither dependency imports the bridge.
- Discovery inspects all compiled provider modules, including private providers,
  but never scans Python packages or creates provider declarations.
- Each discovered handler is identified by canonical `ProviderRef`, not only by
  implementation class or token.
- Handler invocation uses `WorkScopeFactory.run_in()` with the provider owner
  module, preserving exact singleton/request/transient semantics.
- Factory providers without a statically known decorated implementation require
  an explicit binding.
- Explicit bindings suppress auto-discovery of the same canonical provider.
- Commands and queries retain exactly-one-handler validation.
- Events retain deterministic compiled-provider registration/scheduling order
  and invoke distinct canonical providers independently; start and completion
  order are not guaranteed.
- Separate keyed dynamic-module providers remain distinct even when they reuse
  one implementation class.

## Failure Behavior

- Multiple distinct discovered command/query providers for one message fail
  during CQRS graph assembly.
- The same canonical provider reached through aliases is registered once.
- Discovered synchronous handlers fail before invocation.
- A discovered provider removed or changed by a testing override is evaluated
  from the final compiled declaration.
- Event failure metadata includes module-qualified provider identity.

## Verification

- command, query, and event handlers need only one ToriPy-CQRS decorator plus a
  direct class entry in module providers;
- private handlers work without exports or CQRS-module imports;
- request/transient handlers receive isolated work scopes;
- duplicate aliases do not duplicate event delivery;
- dynamic-module and duplicate-token execution resolves the exact owner;
- explicit factory bindings continue to work;
- startup, cancellation, cleanup, Starlette coexistence, and isolated artifact
  tests remain green.
- `examples/tori_py/cqrs/advanced` demonstrates the complete discovery, scoped
  dispatch, event fan-out, projection, query, and HTTP adapter workflow.
