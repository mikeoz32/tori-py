# nestpy-microservices

Optional transport-neutral RPC and event delivery integration for Nestpy.

The base package depends only on Nestpy and `msgspec`. RabbitMQ support is
available through the optional `rabbitmq` extra and is deliberately lazy:
importing either the base package or its RabbitMQ facade does not import
`aio_pika` or open a broker connection.

```bash
uv add nestpy-microservices
uv add "nestpy-microservices[rabbitmq]"
```

The package architecture and implementation phases are documented in the
repository-level `NESTPY_MICROSERVICES_ARCHITECTURE.md` and
`spec/nestpy-microservices/README.md` files.
