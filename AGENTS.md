# Repository Notes

## Project
- This is planned as a social network for the kinky community: user profiles, posts on profiles and in groups, plus private and group chats.
- The first implementation target is a reusable CQRS library, not the social-network domain itself.

## Backend
- Target Python version: 3.14.
- Backend direction: FastAPI with asynchronous SQLAlchemy, PostgreSQL/Citus, and possibly Dragonfly/Redis plus RabbitMQ.
- Frontend is undecided between Nuxt and Elixir Phoenix LiveView; do not scaffold either until that decision is explicit.

## Development
- ALWAYS use `uv` exclusively for Python environments, dependencies, commands, tests, and services.
- Add dependencies with `uv`; run tests and services with `uv`.
- Run quality checks through `uv`: `uv run ruff check .`, `uv run ruff format --check .`, and `uv run ty check packages/cqrs-core/src packages/cqrs-core/tests packages/cqrs-fastapi/src packages/cqrs-fastapi/tests packages/nestpy-sqlalchemy/src packages/nestpy-sqlalchemy/tests`.

## CQRS Library
- Initial workspace boundary: framework-agnostic core package plus a separate FastAPI adapter; core must not depend on FastAPI, Pydantic, SQLAlchemy, or a DI framework.
- Preserve clear boundaries between commands, queries, domain/application logic, and infrastructure; do not copy NestJS internals mechanically into Python.
- The agreed first-slice architecture, implementation order, and non-goals are recorded in `CQRS_IMPLEMENTATION_PLAN.md`.
- Treat privacy, access control, moderation, and safety as core domain concerns for the future profiles, groups, posts, and chats rather than later add-ons.

## Nestpy SQLAlchemy
- The async SQLAlchemy lifecycle/DI integration and its implementation order are recorded in `NESTPY_SQLALCHEMY_ARCHITECTURE.md`, `NESTPY_SQLALCHEMY_IMPLEMENTATION_PLAN.md`, and `spec/nestpy-sqlalchemy/README.md`.
- Keep transactions native and explicit through `AsyncSession.begin()`; the integration must not add CQRS, event-sourcing, repository generation, model scanning, or startup migrations.
