# Why Nestpy

Nestpy is useful when application composition should stay inspectable as a
project grows. Modules declare their providers and controllers directly;
provider visibility across modules is explicit; and application startup and
shutdown own managed resources.

It takes inspiration from the useful vocabulary of NestJS, but it is not a
Python port and does not claim feature parity. Nestpy uses Python constructor
annotations, async application factories, and explicit ASGI integration.

Use Nestpy when its module and lifecycle model helps. Use Starlette directly
when a smaller, unstructured application better fits the problem.
