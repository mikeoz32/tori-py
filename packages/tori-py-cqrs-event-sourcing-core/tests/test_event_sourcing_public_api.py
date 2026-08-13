from pathlib import Path

import tori_py_cqrs_event_sourcing_core


def test_public_facade_exposes_application_contracts() -> None:
    expected = {
        "AggregateCommitStateError",
        "AggregateEnlistedError",
        "AggregateError",
        "AggregateFaultedError",
        "AggregateLifecycleError",
        "AggregateNotFoundError",
        "AggregateOwnershipError",
        "AggregateReplayError",
        "AggregateRoot",
        "AggregateStreamMismatchError",
        "AggregateTypeMismatchError",
        "AppendEvent",
        "CommitResult",
        "CommitResultMismatchError",
        "ConfirmedCommit",
        "ConfirmedCommitCleanupError",
        "ConfirmedCommitError",
        "ConfirmedNonCommit",
        "DuplicateAggregateSaveError",
        "DuplicateEventIdError",
        "DuplicateEventSchemaError",
        "DuplicateStreamAppendError",
        "DuplicateStreamAggregateError",
        "EncodedEvent",
        "EventCodecError",
        "EventDecoder",
        "EventEncoder",
        "EventMetadata",
        "EventSchema",
        "EventSchemaRegistry",
        "EventSourcedRepository",
        "EventSourcingError",
        "EventSourcingLimits",
        "EventSourcingUnitOfWork",
        "EventSourcingValidationError",
        "EventStore",
        "EventStoreError",
        "EventStoreTransaction",
        "EventStoreTransactionError",
        "EventUpcastError",
        "EventUpcaster",
        "InMemoryEventStore",
        "IndeterminateCommitError",
        "IndeterminateCommit",
        "InvalidEventMetadataError",
        "InvalidEventRecordError",
        "InvalidStreamIdError",
        "OptimisticConcurrencyError",
        "PendingEvent",
        "RecordedEvent",
        "ResourceLimitError",
        "SchemaError",
        "SchemaRegistryFrozenError",
        "SchemaRegistryNotFrozenError",
        "SchemaValidationError",
        "StoredEvent",
        "StreamId",
        "UnitOfWorkError",
        "UnitOfWorkLifecycleError",
        "UnitOfWorkOutcome",
        "UnknownEventSchemaError",
        "UnsupportedEventSchemaVersionError",
    }
    assert set(tori_py_cqrs_event_sourcing_core.__all__) == expected


def test_package_includes_type_marker_and_readme() -> None:
    package_root = Path(__file__).parents[1]
    assert (
        package_root / "src" / "tori_py_cqrs_event_sourcing_core" / "py.typed"
    ).is_file()
    assert (package_root / "README.md").is_file()
