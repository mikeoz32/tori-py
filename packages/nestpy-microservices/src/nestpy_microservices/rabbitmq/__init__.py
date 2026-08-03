"""Lazy RabbitMQ integration facade."""

from nestpy_microservices.rabbitmq.dependencies import require_aio_pika

__all__ = ["require_aio_pika"]
