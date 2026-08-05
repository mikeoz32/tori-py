# nestpy-microservices

Optional transport-neutral RPC and event delivery integration for Nestpy.

## Implementation Status

The MS0-MS8 capability set is implemented in the repository worktree. MS9 is
partial/in progress: RabbitMQ event routing, topology, transport mechanics, and
event-mode tests are implemented, but the required application-facing
`EventDispatcher` API owned by the local service root remains. MS10 failure
hardening and MS11 documentation, artifact, quality, and release gates are not
complete; broker restart and network-blackhole recovery are not proven.

The base package depends only on Nestpy and `msgspec`. RabbitMQ support is
available through the optional `rabbitmq` extra and is deliberately lazy:
importing either the base package or its RabbitMQ facade does not import
`aio_pika` or open a broker connection.

```bash
uv add nestpy-microservices
uv add "nestpy-microservices[rabbitmq]"
```

The package architecture and current phase status are documented in the
repository-level `NESTPY_MICROSERVICES_ARCHITECTURE.md`,
`NESTPY_MICROSERVICES_IMPLEMENTATION_PLAN.md`, and
`spec/nestpy-microservices/README.md` files.
