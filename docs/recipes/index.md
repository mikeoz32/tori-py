# Recipes

Recipes combine public APIs around one application problem. They are not new
framework features and do not weaken normal module visibility, scope, lifecycle,
or delivery contracts.

## Available recipes

| Recipe | Outcome |
| --- | --- |
| [Repository Provider](repository-provider.md) | Bind an application repository interface to an implementation and replace the exported token in tests |
| [Authorization and Errors](authorization-and-errors.md) | Keep policy in a provider, enforce it with a guard, and map owned domain failures without leaking internals |
| [External Resources](external-resources.md) | Give singleton and request resources explicit ownership and deterministic cleanup |
| [Background Work](background-work.md) | Avoid escaped request dependencies and execute non-HTTP work in fresh tracked scopes |

## Shared rules

- Provider declarations are explicit. A decorator does not scan or register a
  package.
- A token is visible only locally, through a direct import's explicit export, or
  through an explicitly global module export.
- Singleton providers cannot depend on request-scoped providers. Use
  `WorkScopeFactory` to open fresh application-tracked work scopes.
- Managed resources close in reverse acquisition order. Startup rollback and
  normal shutdown use the same ownership model.
- Request-scoped values, resolvers, and execution contexts must not escape their
  scope. A closed lease raises `ScopeClosedError` instead of silently resolving
  new dependencies.
- Tests replace public exported providers before graph compilation and close the
  resulting `TestingApplication`.
- In-memory repositories, transports, stores, and logs are test or example
  boundaries unless their documentation explicitly claims durability.

Package integrations retain their own contracts. SQLAlchemy repositories share
the singleton `EntityManager`'s lexical transaction; CQRS invocations receive a
fresh work scope; microservice deliveries and persistent-stream records have
at-least-once behavior. A recipe does not make those operations atomic with one
another.
