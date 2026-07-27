# OA0: Workspace and Mapping Contract

## Deliverables

- `packages/nestpy-openapi`, `py.typed`, exact facade, and artifact verification.
- Public `compile_controller_routes(module_id, controller)` in `nestpy.http`.
- Compatible trailing `RoutePlan.return_annotation` field.
- Graph route compilation delegated to the per-controller compiler.

## Required Behavior

- The helper reads canonical Nestpy controller/route/status/binding metadata.
- The helper returns immutable unbound plans for exactly one controller.
- Graph compilation retains graph-wide exact duplicate checks.
- Existing RoutePlan construction remains compatible.
- `StarletteAdapter`, body handling, and response encoding remain unchanged.

## Tests

- Parameter and return annotations, paths, statuses, pipeline mappings.
- Invalid declarations and per-controller duplicates.
- Graph-wide duplicates remain rejected.
- No request-time signature inspection.
- Existing Nestpy HTTP regressions pass.
