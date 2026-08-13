from tori_py_persistent_streams_core import PersistentStreamsError


class RabbitMqPersistentStreamsError(PersistentStreamsError):
    pass


class TopologyConflictError(RabbitMqPersistentStreamsError):
    pass


class PublishIndeterminateError(RabbitMqPersistentStreamsError):
    pass


class EnvelopeError(RabbitMqPersistentStreamsError, ValueError):
    pass


__all__ = [
    "EnvelopeError",
    "PublishIndeterminateError",
    "RabbitMqPersistentStreamsError",
    "TopologyConflictError",
]
