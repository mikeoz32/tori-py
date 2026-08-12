from __future__ import annotations

import math
import ssl
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any


def _positive_number(value: int | float, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


def _positive_int(value: int, name: str, maximum: int = 2**31 - 1) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a positive integer")
    if not 0 < value <= maximum:
        raise ValueError(f"{name} must be between 1 and {maximum}")


class DeclarationMode(StrEnum):
    CREATE = "create"
    REQUIRE_EXISTING = "require_existing"


class SaslMechanism(StrEnum):
    PLAIN = "PLAIN"
    EXTERNAL = "EXTERNAL"


@dataclass(frozen=True, slots=True)
class RabbitMqTlsOptions:
    ca_file: str
    certificate_file: str | None = None
    private_key_file: str | None = None
    server_hostname: str | None = None

    def __post_init__(self) -> None:
        if not self.ca_file:
            raise ValueError("ca_file must be non-empty")
        if (self.certificate_file is None) != (self.private_key_file is None):
            raise ValueError(
                "client certificate and private key must be supplied together"
            )
        if self.server_hostname is not None and not self.server_hostname:
            raise ValueError("server_hostname must be non-empty when supplied")

    def create_context(self) -> ssl.SSLContext:
        context = ssl.create_default_context(cafile=str(Path(self.ca_file)))
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        if self.certificate_file is not None:
            context.load_cert_chain(self.certificate_file, self.private_key_file)
        return context


@dataclass(frozen=True, slots=True)
class RabbitMqConnectionOptions:
    host: str
    username: str
    password: str = field(repr=False)
    port: int = 5552
    vhost: str = "/"
    heartbeat: int = 60
    frame_max: int = 1_048_576
    load_balancer_mode: bool = False
    advertised_host: str | None = None
    sasl_mechanism: SaslMechanism = SaslMechanism.PLAIN
    tls: RabbitMqTlsOptions | None = None
    connection_name: str = "persistent-streams"

    def __post_init__(self) -> None:
        for name in ("host", "username", "vhost", "connection_name"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.password, str):
            raise TypeError("password must be a string")
        for value, name in (
            (self.port, "port"),
            (self.heartbeat, "heartbeat"),
            (self.frame_max, "frame_max"),
        ):
            _positive_int(value, name, 65535 if name == "port" else 2**31 - 1)
        if self.advertised_host is not None and not self.advertised_host:
            raise ValueError("advertised_host must be non-empty when supplied")
        if not isinstance(self.sasl_mechanism, SaslMechanism):
            raise TypeError("sasl_mechanism must be SaslMechanism")
        if self.sasl_mechanism is SaslMechanism.EXTERNAL and self.tls is None:
            raise ValueError("EXTERNAL SASL requires TLS")
        if (
            self.tls is not None
            and self.tls.server_hostname is not None
            and self.tls.server_hostname != self.endpoint_host
        ):
            raise ValueError(
                "TLS server_hostname must match the configured advertised endpoint"
            )

    @property
    def endpoint_host(self) -> str:
        return self.advertised_host or self.host

    def driver_kwargs(self) -> dict[str, Any]:
        from rstream import SlasMechanism

        mechanism = (
            SlasMechanism.MechanismExternal
            if self.sasl_mechanism is SaslMechanism.EXTERNAL
            else SlasMechanism.MechanismPlain
        )
        return {
            "host": self.endpoint_host,
            "port": self.port,
            "username": self.username,
            "password": self.password,
            "vhost": self.vhost,
            "heartbeat": self.heartbeat,
            "frame_max": self.frame_max,
            "load_balancer_mode": self.load_balancer_mode,
            "connection_name": self.connection_name,
            "sasl_configuration_mechanism": mechanism,
            "ssl_context": None if self.tls is None else self.tls.create_context(),
        }


@dataclass(frozen=True, slots=True)
class RabbitMqPersistentStreamsOptions:
    connection: RabbitMqConnectionOptions
    declaration: DeclarationMode = DeclarationMode.CREATE
    max_age_seconds: int = 604_800
    max_length_bytes: int = 1_073_741_824
    max_segment_size_bytes: int = 100_000_000
    initial_credit: int = 1
    callback_queue_capacity: int = 128
    max_pending_count: int = 1024
    max_pending_bytes: int = 64 * 1024 * 1024
    max_streams: int = 1024
    max_named_producers: int = 1024
    broker_managed_single_instance: bool = False
    confirm_timeout: float = 10.0
    operation_timeout: float = 10.0
    close_timeout: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.connection, RabbitMqConnectionOptions):
            raise TypeError("connection must be RabbitMqConnectionOptions")
        if not isinstance(self.declaration, DeclarationMode):
            raise TypeError("declaration must be DeclarationMode")
        for name in (
            "max_age_seconds",
            "max_length_bytes",
            "max_segment_size_bytes",
            "initial_credit",
            "callback_queue_capacity",
            "max_pending_count",
            "max_pending_bytes",
            "max_streams",
            "max_named_producers",
        ):
            _positive_int(getattr(self, name), name, 2**63 - 1)
        for name in ("confirm_timeout", "operation_timeout", "close_timeout"):
            _positive_number(getattr(self, name), name)
        if not isinstance(self.broker_managed_single_instance, bool):
            raise TypeError("broker_managed_single_instance must be a boolean")
        if self.initial_credit != 1:
            raise ValueError(
                "initial_credit must be 1 for the audited bounded-frame contract"
            )
        if self.max_segment_size_bytes > self.max_length_bytes:
            raise ValueError("max_segment_size_bytes must not exceed max_length_bytes")

    @property
    def declaration_arguments(self) -> MappingProxyType[str, object]:
        return MappingProxyType(
            {
                "max-age": f"{self.max_age_seconds}s",
                "max-length-bytes": self.max_length_bytes,
                "stream-max-segment-size-bytes": self.max_segment_size_bytes,
            }
        )
