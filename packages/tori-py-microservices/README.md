# tori-py-microservices

Optional transport-neutral RPC and event delivery integration for ToriPy.

## Release Status

Version `0.1.0` is the initial beta release. The MS0-MS9 capability set includes
the root-owned application-facing `EventDispatcher`, complete real-broker event
cardinality, offline ephemeral behavior, and reliable-broadcast restart
retention. MS10 failure hardening and MS11 acceptance are implemented;
broker application restart, pending-RPC reconnect behavior, confirm/timeout
classification, handler/reply blackholes, bounded retry/DLX, malformed schema
dead-lettering, deleted reply routes, and active-RPC forced shutdown are
covered by the current MS10 slice. Operators must complete the checks in the
[operations guide](docs/OPERATIONS.md) before deployment.

The base package depends only on ToriPy and `msgspec`. RabbitMQ support is
available through the optional `rabbitmq` extra and is deliberately lazy:
importing either the base package or its RabbitMQ facade does not import
`aio_pika` or open a broker connection.

## Operations And Security

RabbitMQ status transitions are distinct and readiness is not inferred from a
successful publish. An accepted or indeterminate RPC is never automatically
republished. Monitor connection/transport status, pending RPC count, queue
depth, redelivery, dead-letter depth, and publisher-confirm latency using
bounded labels only; never use payloads, member identifiers, credentials,
reply tokens, or remote error text as metric or log fields.

Production deployments should use TLS, one credential and vhost permission set
per service, and the minimum `configure`, `write`, and `read` permissions for
the service's exchanges, queues, bindings, and reply route. Restrict target
routing keys with RabbitMQ topic permissions when shared RPC exchanges are
used. TLS verification failures and all indeterminate publication/settlement
outcomes must remain typed failures.

```bash
uv add tori-py-microservices
uv add "tori-py-microservices[rabbitmq]"
```

The package architecture and phase status are documented in the
[architecture](https://github.com/mikeoz32/tori-py/blob/main/TORI_PY_MICROSERVICES_ARCHITECTURE.md),
[implementation plan](https://github.com/mikeoz32/tori-py/blob/main/TORI_PY_MICROSERVICES_IMPLEMENTATION_PLAN.md),
and [specification](https://github.com/mikeoz32/tori-py/blob/main/spec/tori-py-microservices/README.md).

## MS11 Guides

- [User guide](docs/USER_GUIDE.md)
- [Operations and release guide](docs/OPERATIONS.md)
- [Executable examples](https://github.com/mikeoz32/tori-py/tree/main/examples/tori_py/microservices)

## Event Publication

Import a keyed adapter root through `MicroservicesModule.for_root(...)`. The
module exports one managed `EventDispatcher` that application providers can
inject:

```python
from tori_py_microservices import EventDispatcher


class ProfilePublisher:
    def __init__(self, events: EventDispatcher) -> None:
        self.events = events

    async def profile_created(self, payload: object) -> None:
        await self.events.publish(
            "profile-created",
            1,
            payload,
            headers={"trace": "safe-application-metadata"},
        )
```

The root supplies the source namespace, service, contract version, exchange,
and routing prefix. Callers can supply only event alias, schema version, payload,
headers, correlation/causation IDs, an optional original UTC `occurred_at`, and
`require_route`. Message IDs and default occurrence times are generated. Zero
subscribers succeeds by default; `require_route=True` raises
`TransportUnroutableError` when no binding exists.

The dispatcher starts and closes its own event-only client transport with the
application and drains accepted publications during quiescence. Direct
`ServerTransportFactory` roots remain supported for inbound-only use, but do not
export `EventDispatcher`; use a `KeyedTransportFactoryReference` whose adapter
provides both exact factory tokens when publication is required.
