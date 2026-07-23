# Nestpy CQRS Integration Plan

This directory specifies the optional `nestpy-cqrs` package. It consumes public
Nestpy contracts and `cqrs-core` without creating reverse dependencies. C0-C3
are implemented.

Implementation order:

1. [C0: Workspace and Contracts](phase-c0-workspace-and-contracts.md)
2. [C1: Scoped Module and Lifecycle](phase-c1-module-and-lifecycle.md)
3. [C2: Automatic Handler Discovery](phase-c2-automatic-discovery.md)
4. [C3: Invocation Pipeline](phase-c3-invocation-pipeline.md)

Every phase runs repository pytest, Ruff, formatting, and type checks through
`uv`. The package must also build as an isolated wheel and source distribution.
