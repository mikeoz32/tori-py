# Phase N1: Module Compiler and Visibility

## Purpose

Compile static and deferred dynamic modules plus provider declarations into an
immutable, validated graph. N1 produces plans only; it does not instantiate
providers or open resources.

## Entry Criteria

- N0 declarations and import boundaries pass.
- Provider forms, module metadata, tokens, and diagnostics are stable.

## Internal Models

N1 introduces internal frozen models:

```text
ModuleId
ProviderKey
ProviderRef
DependencyPlan
ProviderPlan
ModulePlan
GraphShape
CompiledGraph
```

Internal identities MUST NOT leak through required user APIs or public error
attributes. Diagnostics MAY render human-readable identities.

## Static Modules

A static module is identified by its class. Repeated imports reuse one node.
Module classes MUST have no required constructor arguments; instances and hooks
are N2 concerns.

A module declares imports, providers, controllers, exports, and `global_`.
Controllers compile as mandatory singleton class providers.

## Deferred Dynamic Modules

`DeferredModule` holds a module class, explicit key, and sync/async materializer.
N1 materializes it during graph compilation.

Rules:

- the same descriptor object may be imported repeatedly and materializes once;
- another descriptor object with the same `(module class, key)` is an error;
- key `"static"` is reserved;
- static and dynamic nodes of the same module class cannot coexist;
- different keys create separate nodes;
- no arbitrary `ModuleSpec` equality or configuration hashing is used;
- materialization does not open providers/resources or invoke hooks.

## Compilation Stages

The compiler executes deterministic stages:

1. materialize module descriptors;
2. normalize immutable module specs;
3. build the import graph and detect cycles;
4. assign dependency-first module order with declaration-order tie-breaking;
5. validate local provider/controller declarations;
6. build exports and global-module sets;
7. compile provider constructor/factory annotations;
8. build visibility;
9. resolve aliases;
10. detect provider and alias cycles;
11. validate transitive scope paths;
12. freeze plans.

Independent diagnostics within one stage SHOULD be collected and sorted before
raising. Later stages MUST NOT run when earlier structural errors make their
output unreliable.

## Visibility

For `(module, token)`, resolution is:

1. local provider;
2. explicit export from a direct import;
3. explicit export from a global module.

Same-level multiple matches are ambiguity errors. A local binding shadows
imports; a direct import shadows globals. Exports are not automatically
transitive. A module may explicitly re-export a token visible through a direct
import. A global token does not become re-exportable merely because it is
globally visible.

## Dependency Compilation

Use `typing.get_type_hints(..., include_extras=True)` once during compilation.

Rules:

- class annotation chooses the class token;
- `Annotated[T, Inject(token)]` overrides it;
- multiple `Inject` markers are invalid;
- required unannotated parameters are invalid;
- variadic injection is invalid;
- an annotated parameter with a default uses its default unless explicit
  `Inject` is present;
- factories may be sync or async;
- unregistered classes are not auto-registered.

Store qualified provider keys in plans. Runtime code MUST NOT repeat annotation
inspection or unqualified visibility lookup.

## Alias and Scope Validation

Aliases resolve to one canonical provider identity and inherit its scope/cache/
resource ownership. Detect alias-only and mixed dependency cycles.

Scope validation traverses complete paths. A singleton reaching a request
provider through any number of transient/alias edges is an error. Diagnostics
include the full provider and scope path.

## Graph Errors

N1 emits typed diagnostics for:

- module cycles and static/dynamic conflicts;
- malformed/failed materialization as `module.materialization_error`;
- required module constructor arguments as `module.invalid_constructor`;
- duplicate local tokens;
- invalid exports;
- unresolved or ambiguous dependencies;
- provider/alias cycles;
- invalid provider signatures;
- scope violations;
- non-singleton controllers.

## Explicit Non-Goals

N1 MUST NOT:

- instantiate module/provider/controller objects;
- open context managers;
- invoke lifecycle hooks;
- create request scopes;
- compile Starlette routes;
- parse settings sources;
- apply testing overrides.

## Tests

Tests MUST cover:

1. repeated static imports reuse one node;
2. same deferred object reuses one node/materialization;
3. different descriptor with same identity fails before second materialization;
4. async materializer is awaited and the same descriptor materializes exactly
   once;
5. static/dynamic class conflict;
6. dynamic key isolation;
7. module cycle diagnostics;
8. local/direct/global visibility precedence;
9. ambiguity at direct/global levels;
10. explicit re-export and private provider isolation;
11. constructor/factory annotation plans;
12. defaults and `Inject` overrides;
13. provider and alias cycles;
14. alias canonical identity/scope;
15. direct and indirect singleton-to-request violations;
16. deterministic plan/diagnostic order;
17. reserved dynamic key rejection;
18. malformed materializer result;
19. duplicate local token and invalid export;
20. unresolved dependency and invalid signature;
21. module class with required constructor arguments;
22. controller declarations accept classes only and compile only as singleton;
23. compilation never instantiates providers/modules/controllers, enters
    resources, or invokes hooks;
24. monkeypatched/signature-count instrumentation proves provider annotations
    are inspected during compilation only, never runtime resolution;
25. compiled plans contain no Starlette types.

## Exit Criteria

N1 is complete when arbitrary valid module/provider graphs compile to immutable
runtime plans, every invalid visibility/dependency/scope graph fails before
instantiation, and focused tests prove deterministic behavior.
