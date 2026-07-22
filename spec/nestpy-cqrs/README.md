# Nestpy CQRS Integration Plan

This directory specifies the optional `nestpy-cqrs` package. It consumes public
Nestpy N0-N7 and `cqrs-core` contracts without creating reverse dependencies.

Implementation order:

1. [C0: Workspace and Contracts](phase-c0-workspace-and-contracts.md)
2. [C1: Scoped Module and Lifecycle](phase-c1-module-and-lifecycle.md)
3. [C2: Automatic Handler Discovery](phase-c2-automatic-discovery.md)

Every phase runs repository pytest, Ruff, formatting, and type checks through
`uv`. The package must also build as an isolated wheel and source distribution.
