# Repository Notes

## Project
- This is planned as a social network for the kinky community: user profiles, posts on profiles and in groups, plus private and group chats.
- The reusable framework and CQRS foundation is complete enough to begin the Kinker product application. The accepted initial product architecture is recorded in `KINKER_APPLICATION_ARCHITECTURE.md`.
- The product domain vision, ubiquitous language, context map, cross-context policies, and bounded-context specifications are governed by `spec/kinker/README.md`; update the owning specification before choosing ambiguous business behavior in code.

## Backend
- Target Python version: 3.14.
- The Kinker product backend is a modular monolith built with Nestpy/Starlette, `nestpy-cqrs`, `nestpy-sqlalchemy`, PostgreSQL, and application-owned Alembic migrations. Use `nestpy-sqlalchemy` for lifecycle, DI, repositories, sessions, and transactions rather than adding a raw application SQLAlchemy integration.
- Product persistence starts with CQRS and `nestpy-sqlalchemy`; add event sourcing later only to bounded contexts where it has a concrete benefit. The reusable `cqrs-fastapi` adapter is not the Kinker application stack.
- Authentication is delegated to an external OIDC provider. The first product slice is identity-linked member profile onboarding with a unique handle, display name, visibility, and an 18+ attestation that does not store a date of birth.
- The accepted implementation order and executable phase map for that slice are recorded in `KINKER_MEMBERS_PROFILES_IMPLEMENTATION_PLAN.md` and `spec/kinker/members-and-profiles/implementation/README.md`.
- Frontend is undecided between Nuxt and Elixir Phoenix LiveView; do not scaffold either until that decision is explicit.

## Development
- ALWAYS use `uv` exclusively for Python environments, dependencies, commands, tests, and services.
- Add dependencies with `uv`; run tests and services with `uv`.
- Run quality checks through `uv`: `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check src/kinker tests packages/cqrs-core/src packages/cqrs-core/tests packages/cqrs-event-sourcing/src packages/cqrs-event-sourcing/tests packages/cqrs-fastapi/src packages/cqrs-fastapi/tests packages/nestpy/src packages/nestpy/tests packages/nestpy-cqrs/src packages/nestpy-cqrs/tests packages/nestpy-cqrs-event-sourcing/src packages/nestpy-cqrs-event-sourcing/tests packages/nestpy-sqlalchemy/src packages/nestpy-sqlalchemy/tests examples/nestpy`.

## CQRS Library
- Initial workspace boundary: framework-agnostic core package plus a separate FastAPI adapter; core must not depend on FastAPI, Pydantic, SQLAlchemy, or a DI framework.
- Preserve clear boundaries between commands, queries, domain/application logic, and infrastructure; do not copy NestJS internals mechanically into Python.
- The agreed first-slice architecture, implementation order, and non-goals are recorded in `CQRS_IMPLEMENTATION_PLAN.md`.
- The framework-neutral event-sourcing package, its implementation order, and adapter boundaries are recorded in `CQRS_EVENT_SOURCING_IMPLEMENTATION_PLAN.md` and `spec/cqrs-event-sourcing/README.md`.
- The planned Nestpy-native event-sourcing integration, automatic command transaction semantics, and decorated repository API are recorded in `NESTPY_CQRS_EVENT_SOURCING_ARCHITECTURE.md` and `spec/nestpy-cqrs-event-sourcing/README.md`.
- Treat privacy, access control, moderation, and safety as core domain concerns for the future profiles, groups, posts, and chats rather than later add-ons.

## Nestpy SQLAlchemy
- The async SQLAlchemy lifecycle/DI integration and its implementation order are recorded in `NESTPY_SQLALCHEMY_ARCHITECTURE.md`, `NESTPY_SQLALCHEMY_IMPLEMENTATION_PLAN.md`, and `spec/nestpy-sqlalchemy/README.md`.
- Keep engine, session-factory, SessionManager, EntityManager, and explicitly registered repository providers singleton; managers must create short-lived sessions per operation without ambient state. Default and decorated custom repositories are allowed, but the integration must not add CQRS, event-sourcing, model scanning, generated repository classes, a custom query language, or startup migrations.
