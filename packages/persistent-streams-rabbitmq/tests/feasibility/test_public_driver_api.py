from __future__ import annotations

import inspect
import ssl

import rstream
from rstream import Consumer, Producer, SuperStreamConsumer, SuperStreamProducer


def test_supported_public_facade_and_python_version() -> None:
    assert rstream.__version__ == "1.0.1"
    assert {
        "AMQPMessage",
        "Consumer",
        "ConsumerOffsetSpecification",
        "OffsetType",
        "Producer",
        "Properties",
        "SuperStreamConsumer",
        "SuperStreamCreationOption",
        "SuperStreamProducer",
    }.issubset(rstream.__all__)


def test_public_resource_and_delivery_api_shape() -> None:
    assert {
        "close",
        "create_stream",
        "delete_stream",
        "send",
        "send_batch",
        "send_wait",
        "start",
        "stream_exists",
    }.issubset(dir(Producer))
    assert {
        "close",
        "create_stream",
        "delete_stream",
        "query_offset",
        "store_offset",
        "subscribe",
        "unsubscribe",
    }.issubset(dir(Consumer))
    assert {"create_super_stream", "delete_super_stream", "send"}.issubset(
        dir(SuperStreamProducer)
    )
    assert {"create_super_stream", "delete_super_stream", "subscribe"}.issubset(
        dir(SuperStreamConsumer)
    )


def test_required_bounds_stats_and_sequence_queries_are_not_public() -> None:
    assert "query_publisher_sequence" not in dir(Producer)
    assert "stream_stats" not in dir(Producer)
    assert "stream_stats" not in dir(Consumer)
    assert "available_bounds" not in dir(Consumer)


def test_tls_is_an_ssl_context_constructor_input() -> None:
    for native_type in (Producer, Consumer, SuperStreamProducer, SuperStreamConsumer):
        parameter = inspect.signature(native_type).parameters["ssl_context"]
        assert parameter.default is None
        assert "SSLContext" in str(parameter.annotation)

    context = ssl.create_default_context()
    producer = Producer(
        "localhost",
        username="streams",
        password="streams",
        ssl_context=context,
    )
    assert producer is not None
