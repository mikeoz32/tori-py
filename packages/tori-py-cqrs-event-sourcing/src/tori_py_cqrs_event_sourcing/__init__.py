"""ToriPy CQRS integration for framework-neutral event sourcing."""

from tori_py_cqrs_event_sourcing.decorators import (
    aggregate_repository,
    event_sourcing_transaction,
    use_event_sourcing,
)
from tori_py_cqrs_event_sourcing.errors import (
    CommandCancellationError,
    CommandFinalizationPhase,
    CommandSynchronizationStateError,
    CommandTransactionUnavailableError,
    ConfirmedCommandFinalizationError,
    ConfirmedNonCommitFinalizationError,
    CqrsEventSourcingConfigurationError,
    CqrsEventSourcingError,
    IndeterminateCommandFinalizationError,
)
from tori_py_cqrs_event_sourcing.module import CqrsEventSourcingModule
from tori_py_cqrs_event_sourcing.options import (
    CqrsEventSourcingOptions,
    UnitOfWorkFactory,
    default_unit_of_work_factory,
)
from tori_py_cqrs_event_sourcing.synchronization import CommandSynchronization
from tori_py_cqrs_event_sourcing.tokens import (
    get_command_synchronization_token,
    get_event_store_token,
    get_schema_registry_token,
    get_transaction_interceptor_token,
)

__all__ = [
    "CommandCancellationError",
    "CommandFinalizationPhase",
    "CommandSynchronization",
    "CommandSynchronizationStateError",
    "CommandTransactionUnavailableError",
    "ConfirmedCommandFinalizationError",
    "ConfirmedNonCommitFinalizationError",
    "CqrsEventSourcingConfigurationError",
    "CqrsEventSourcingError",
    "CqrsEventSourcingModule",
    "CqrsEventSourcingOptions",
    "IndeterminateCommandFinalizationError",
    "UnitOfWorkFactory",
    "aggregate_repository",
    "default_unit_of_work_factory",
    "event_sourcing_transaction",
    "get_command_synchronization_token",
    "get_event_store_token",
    "get_schema_registry_token",
    "get_transaction_interceptor_token",
    "use_event_sourcing",
]
