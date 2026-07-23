# C3: Invocation Pipeline

## Purpose

Expose a public Nestpy-style interceptor seam around CQRS handler invocation
without coupling `nestpy-cqrs` to persistence or HTTP.

## Contract

- Public `CqrsInvocationContext` implements Nestpy `ExecutionContext`.
- Standard properties are exact: kernel application ID, string module label,
  `route_id=None`, `request_id=None`, scoped resolver, immutable metadata, and
  `execution_kind="cqrs"`.
- Exact `owner_module: ModuleId` and `handler_ref: ProviderRef` are separate
  properties.
- Public `CqrsInvocationInterceptor` uses a one-shot async `next` callback.
- Public `CqrsInterceptorPhase` has `OUTER`, `GRAPH`, and `HANDLER`; public
  `CqrsInterceptorBinding` pairs one token/instance with one phase and optional
  allowed handler kinds validated during graph assembly.
- `CqrsModuleOptions` command/query/event interceptor lists are graph phase.
- `use_cqrs_interceptors(*items, phase=HANDLER)` composes repeated direct
  decorators in visible order and preserves argument order within each.
- Explicit handler bindings accept phased interceptor bindings, including OUTER
  bindings for factory handlers.
- Provider-backed interceptors and the handler resolve lazily in chain order.
- Provider tokens use exact handler-owner visibility and normal scopes.
- Direct instances are externally owned.
- Explicit handler bindings accept interceptor metadata for factory providers.
- Class metadata is read only when the final provider implementation is statically
  knowable; factories are never constructed during discovery.
- `CqrsInvocationContext.completion` exposes public
  `CqrsInvocationCompletion.register(key, mapper)`, accepting unique, pure,
  synchronous completion mappers until the chain returns, then freezing.
- After scope closure, the owner invokes mappers in reverse order with a
  `CqrsScopeCompletion` containing typed result availability, body error, and
  scope finalization plus the current composable error; mappers cannot suppress
  existing errors, resolve providers, or perform cleanup.
- Existing handler discovery, transport, and lifecycle behavior is unchanged.
- `CqrsInvocationContext.on_handler_exit()` callbacks run in reverse order at the
  exact terminal boundary before inner interceptors resume; all are attempted,
  handler failure remains primary, and callback control flow is preserved.

## Tests

- Context property mapping and immutable metadata.
- Phase/declaration ordering and reverse unwind.
- One-shot next and lazy construction.
- Private, alias, dynamic, factory, and overridden providers.
- Request/transient/singleton interceptor scopes.
- Handler/interceptor failure, cancellation, and N8 cleanup combinations.
- Terminal callback ordering, multiple failures, handler-error precedence, and
  callback cancellation.
- Duplicate completion keys, freeze timing, reverse mapper composition, mapper
  purity, and transformed-error chaining.
- No HTTP context propagation.

## Exit Criteria

- Optional packages can add scoped invocation behavior using only public APIs.
