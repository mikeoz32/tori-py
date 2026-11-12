"""Persistent stream composition with an in-memory or RabbitMQ adapter."""

import os

from tori_py import DeferredModule
from tori_py_persistent_streams import (
    PersistentStreamsModule,
    PersistentStreamsOptions,
    PersistentStreamsRuntimeOptions,
    PublisherRegistration,
)
from tori_py_persistent_streams.testing import InMemoryPersistentStreamsModule
from tori_py_persistent_streams_core import InMemoryCheckpointStore
from tori_py_persistent_streams_rabbitmq import (
    RabbitMqConnectionOptions,
    RabbitMqPersistentStreamsModule,
    RabbitMqPersistentStreamsOptions,
)

from .activity import TASK_ACTIVITY, TaskActivityPublisher, task_activity_binding


def stream_adapter_module() -> DeferredModule:
    adapter = os.getenv("TASK_API_STREAMS", "memory")
    if adapter == "memory":
        return InMemoryPersistentStreamsModule.for_root()
    if adapter != "rabbitmq":
        raise ValueError("TASK_API_STREAMS must be 'memory' or 'rabbitmq'")
    return RabbitMqPersistentStreamsModule.for_root(
        RabbitMqPersistentStreamsOptions(
            RabbitMqConnectionOptions(
                host=os.getenv("RABBITMQ_STREAM_HOST", "localhost"),
                port=int(os.getenv("RABBITMQ_STREAM_PORT", "5552")),
                username=os.getenv("RABBITMQ_USER", "tutorial"),
                password=os.getenv("RABBITMQ_PASSWORD", "tutorial"),
                connection_name="task-api-activity",
            )
        )
    )


def streams_module() -> DeferredModule:
    return PersistentStreamsModule.for_root(
        PersistentStreamsOptions(
            bindings=(task_activity_binding(InMemoryCheckpointStore()),),
            publishers=(
                PublisherRegistration(TASK_ACTIVITY, protocol=TaskActivityPublisher),
            ),
            runtime=PersistentStreamsRuntimeOptions(
                owner_id="task-api",
                single_instance_consumer_groups=True,
            ),
        ),
        imports=[stream_adapter_module()],
    )
