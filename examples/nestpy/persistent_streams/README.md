# Persistent Streams

[`app.py`](app.py) is a runnable, broker-free `NestApplication` showing a typed DTO
codec, a handler pipe, partition metadata, checkpointed `@stream_handler`
delivery, and one global `PersistentStreamsModule` root. That root composes the
in-memory adapter through its `imports`; `ApplicationModule` imports only the streams
root. An injectable bootstrap provider publishes the demo records after
the stream runtime is ready, and normal application shutdown drains and closes it.
The application factory creates fresh module and adapter composition for every
application instance.

It publishes through all supported application surfaces: raw `StreamPublisher`,
a named `ConfiguredStreamPublisher`, and an explicit Protocol publisher.

```text
uv run python -m examples.nestpy.persistent_streams.app
uv run pytest examples/nestpy/persistent_streams
```

For RabbitMQ, keep the application inventory unchanged and replace only the
adapter composition:

```python
from persistent_streams_rabbitmq import (
    RabbitMqConnectionOptions,
    RabbitMqPersistentStreamsModule,
    RabbitMqPersistentStreamsOptions,
)

rabbit = RabbitMqPersistentStreamsModule.for_root(
    RabbitMqPersistentStreamsOptions(
        RabbitMqConnectionOptions(
            host="streams.example",
            username="application",
            password="secret",
        )
    )
)
streams = PersistentStreamsModule.for_root(options, imports=[rabbit])
```

RabbitMQ startup verifies only the adapter's documented topology facts. Review
the adapter [supported contract and limits](../../../packages/persistent-streams-rabbitmq/README.md)
and its [operations guide](../../../packages/persistent-streams-rabbitmq/OPERATIONS.md)
before production use.
