# MS2: Controller Discovery and Handler Compiler

## Status

Implemented. Direct decorator metadata, graph-aware discovery, exact owner
identity, deterministic registries, and compile-time validation have focused
tests in the package suite.

## Purpose

Compile every decorated method on every explicitly registered ToriPy controller
into one deterministic service registry without endpoint modules, package
scanning, or transport access.

## Public Contracts

- `rpc(method, *, schema_version=1)` direct method decorator.
- `event_handler(source: ServiceIdentity, event, *, schema_version, mode,
  subscription, reliable=None)` direct method decorator.
- `EventDispatchMode` with `SERVICE_POOL`, `SINGLETON`, and `BROADCAST`.
- Parameter markers `Payload`, `Context`, `Headers`, and `Header`.
- Immutable `MessageParameterPlan`, `RpcHandlerPlan`, `EventHandlerPlan`, and
  `ServiceHandlerRegistry` views needed by transports and future tooling.
- Public `compile_controller_message_handlers(module_id, controller)` helper.

## Discovery Contract

- Inject `DiscoveryService`; call `get_controllers()` exactly once per root
  registry assembly.
- Preserve deterministic compiled module/controller declaration order.
- Inspect only direct entries in `controller.__dict__`.
- Ignore undecorated methods and normal HTTP routes without message metadata.
- Permit one method to have an HTTP route and one message mapping only when both
  complete contracts remain independently valid.
- Retain the controller's canonical `ProviderRef` and exact owner `ModuleId`.
- Observe final testing overrides and statically known final implementations.
- Construct no request/transient provider during discovery.

## RPC Compilation

- RPC alias is an explicit stable one-segment method name.
- Aliases are unique application-wide because one application is one service.
- Handler is async and has an explicit return annotation, including explicit
  `None` where appropriate.
- Missing target methods, non-callable overrides, and metadata conflicts fail
  before intake.

## Event Compilation

- Complete source identity, event, schema version, delivery mode, and
  subscription form one explicit consumer contract.
- Source contract version comes from `source`; event payload compatibility comes
  independently from `schema_version`.
- Durable handlers require an explicit stable subscription.
- Event handler is async and returns explicit `None`.
- `SINGLETON` requires a global subscription identity.
- `BROADCAST` records reliability requirements but receives runtime instance
  identity from root options.
- `SERVICE_POOL` and `SINGLETON` reject a `reliable` argument because they are
  unconditionally durable. `BROADCAST` defaults to ephemeral; `reliable=True`
  requires a configured stable instance identity.
- Any duplicate local queue identity is rejected because one broker delivery
  cannot deterministically select two local methods.

## Parameter Compilation

- Every non-`self` parameter has exactly one supported `Annotated` marker.
- At most one complete payload marker exists.
- Field payload/header markers require explicit non-empty source names.
- Context annotations accept the correct base context subtype.
- `Inject` uses normal ToriPy tokens and exact owner visibility.
- Variadic parameters and unresolved annotations are invalid.
- Parameter and return type hints are resolved once during startup.

## Pipeline Compilation

- Controller and method pipeline metadata are captured in declaration order.
- Global options are qualified from the microservices root.
- Controller/method provider tokens are validated from the handler owner module.
- Message enhancer implementation classes must be explicit ToriPy providers;
  the package does not mutate compiled module specs after discovery.
- Direct instances remain externally owned.

## Tests

- Several controllers across several static and keyed dynamic modules.
- Controllers containing HTTP-only, RPC-only, event-only, and mixed methods.
- Direct-only metadata and inherited-method exclusion.
- Duplicate RPC aliases across controllers/modules.
- Duplicate event subscription identities and mode-specific reliability.
- Complete parameter marker, default, annotation, and variadic matrix.
- Exact `ProviderRef` under duplicate controller class/token situations.
- Private dependencies, aliases, global providers, and testing overrides.
- No package scan, provider construction, or transport access.
- Deterministic registry order and immutable plans.

## Exit Criteria

- One application-wide registry fully describes every message entry point before
  a transport starts.
- Controllers require only normal ToriPy module registration and method
  decorators.
