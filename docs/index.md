# Nestpy

Nestpy is a Python application framework for applications that need explicit
module composition, constructor-based dependency injection, and ASGI HTTP
delivery. It uses public Python types and decorators rather than package scans
or a process-global registry.

Start with [Installation](getting-started/installation.md), then build a
[First Application](getting-started/first-application.md).

## What v1 provides

- Explicit modules, provider declarations, exports, and imports.
- Singleton and request-scoped dependency resolution with lifecycle ownership.
- A Starlette ASGI driver for controllers, raw HTTP binding, and pipelines.
- Typed settings, structured logging, test-time provider overrides, and a small
  `nestpy run` command.

## What v1 does not provide

Nestpy does not include persistence, migrations, brokers, CQRS, authentication,
authorization policy implementations, WebSockets, templates, or Pydantic
integration. Applications may integrate those concerns explicitly.

See [Why Nestpy](why-nestpy.md) for the design boundaries.
