from persistent_streams import PersistentStreamsError


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
