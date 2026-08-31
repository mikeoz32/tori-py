# Aggregates and Event Schemas

The framework-neutral event-sourcing model has two synchronous boundaries:

- an `AggregateRoot` applies domain events and records pending occurrences;
- an `EventSchemaRegistry` converts between domain events and stable persisted
  bytes.

Neither boundary performs I/O, resolves dependencies, or publishes messages.

## Installation

```text
uv add tori-py-cqrs-event-sourcing-core
```

The package depends on `tori-py-cqrs-core` for the `Event` marker and requires
Python 3.14.

## Define Events and an Aggregate

Domain methods validate a decision, then call `raise_event()`. `_apply()` is the
single state transition function used for both new events and replayed history.

```python
from dataclasses import dataclass
from uuid import UUID

from tori_py_cqrs_core import Event
from tori_py_cqrs_event_sourcing_core import AggregateRoot


@dataclass(frozen=True, slots=True)
class ProfileOpened(Event):
    display_name: str


@dataclass(frozen=True, slots=True)
class DisplayNameChanged(Event):
    display_name: str


class Profile(AggregateRoot[UUID]):
    def __init__(self, profile_id: UUID) -> None:
        super().__init__(profile_id)
        self.display_name = ""
        self.is_open = False

    def open(self, display_name: str) -> None:
        name = self._valid_name(display_name)
        if self.is_open:
            raise ValueError("profile is already open")
        self.raise_event(ProfileOpened(name))

    def change_display_name(self, display_name: str) -> None:
        if not self.is_open:
            raise ValueError("profile is not open")
        self.raise_event(DisplayNameChanged(self._valid_name(display_name)))

    def _apply(self, event: Event) -> None:
        match event:
            case ProfileOpened(display_name=name):
                self.display_name = name
                self.is_open = True
            case DisplayNameChanged(display_name=name):
                self.display_name = name
            case _:
                raise AssertionError(f"unknown profile event: {event!r}")

    @staticmethod
    def _valid_name(value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("display name cannot be empty")
        return name
```

The important split is:

- domain methods decide whether an event should happen;
- `_apply()` deterministically reflects a fact that already happened.

`_apply()` must be synchronous, deterministic, and free of I/O and external side
effects. It must not call a repository, bus, database, clock, random generator,
or DI container. Domain validation should happen before `raise_event()` so an
event valid for a stream version cannot be rejected during replay.

## Recording Behavior

For a new aggregate:

```python
profile = Profile(profile_id)
profile.open("Alice")
profile.change_display_name("Alicia")

assert profile.display_name == "Alicia"
assert profile.version == 0
assert len(profile.pending_events) == 2
```

`raise_event()` performs this exact local sequence:

1. Require that the aggregate is mutable, not faulted or enlisted.
2. Construct and validate one `PendingEvent` and its metadata.
3. Call `_apply(event)`.
4. Append the pending occurrence only after successful application.

The aggregate's `version` remains the last confirmed committed version. Pending
events are returned as an immutable tuple snapshot in occurrence order.

If `_apply()` raises, the base class cannot prove whether the subclass partially
mutated state. It marks the aggregate faulted, does not record that failing event,
and rejects replay, further events, staging, and commit transitions. Discard and
reload the aggregate.

The event object itself should be effectively immutable. The package validates
that it is a concrete `Event`, but it does not deep-copy arbitrary application
objects and cannot make a mutable event subclass safe after recording.

## Occurrence Metadata

By default, `raise_event()` assigns a UUID once and records the current
timezone-aware UTC time. Supply explicit metadata when correlation, causation,
headers, deterministic tests, or an application-assigned event ID are needed:

```python
from datetime import UTC, datetime
from uuid import uuid4

from tori_py_cqrs_event_sourcing_core import EventMetadata


metadata = EventMetadata(
    event_id=uuid4(),
    occurred_at=datetime.now(UTC),
    correlation_id=uuid4(),
    causation_id=uuid4(),
    headers={"tenant": "north"},
)

profile.raise_event(
    DisplayNameChanged("Alicia"),
    metadata=metadata,
)
```

Metadata requires UUID identities, a timezone-aware timestamp, and UTF-8
string-to-string headers. Headers are copied into an immutable mapping. The same
event ID, occurrence time, correlation, causation, and headers survive encoding,
storage, decoding, and replay.

Do not put delivery attempt numbers in event metadata. Delivery attempts can
change; the event occurrence must remain stable.

## Replay Behavior

Application code normally calls `repository.load()` or `repository.get()` rather
than `_replay()` directly. A repository:

1. Creates a pristine aggregate at version `0`.
2. Reads finite pages from one transaction snapshot.
3. Decodes each `StoredEvent` to a `RecordedEvent`.
4. Passes each contiguous page to aggregate replay.

Replay validates an entire page before applying its first event:

- every value must be `RecordedEvent`;
- all records must use the aggregate's one stream;
- the first version must be current aggregate version plus one;
- every following version must be contiguous;
- no pending event may exist;
- the aggregate must not be enlisted or faulted.

Replay invokes `_apply()` without adding pending events. It advances `version`
after each successful event. A malformed page or any application failure faults
the instance, and the repository never returns that partially replayed object.

## Enlistment and Commit State

`EventSourcedRepository.save()` exclusively enlists an aggregate in one Unit of
Work. While enlisted, the aggregate rejects new domain events, replay, and a
second save. Serialization does not clear pending events.

On confirmed rollback, enlistment is released and pending events remain. On a
validated confirmed commit, the Unit of Work advances the version and clears
the exact staged pending snapshot. On a stale or indeterminate result, the
aggregate is faulted and pending events remain only as diagnostic state.

These lifecycle transitions are base-owned. Aggregate subclasses implement
`_apply()` and domain methods; they should not override or call storage commit
bookkeeping.

## Event Record Stages

The public immutable values make representation changes explicit:

| Type | Important fields | Created by |
| --- | --- | --- |
| `PendingEvent` | concrete event, `EventMetadata` | `AggregateRoot.raise_event()` |
| `EncodedEvent` | stable `event_type` alias, `schema_version`, payload bytes | schema registry |
| `AppendEvent` | encoded event and occurrence metadata | schema registry |
| `StoredEvent` | stream ID/version, global position, append event | event store |
| `RecordedEvent` | stream/order fields, current schema identity, decoded event, metadata | schema registry |

Versions and positions are positive non-boolean integers. A `StreamId` has a
non-empty trimmed printable category and key. Event aliases are also non-empty,
trimmed, printable UTF-8 strings.

## Define Stable Schemas

The registry does not choose JSON or generate codecs. Supply deterministic
bytes encoders and decoders explicitly:

```python
import json

from tori_py_cqrs_event_sourcing_core import (
    EventSchema,
    EventSchemaRegistry,
)


def encode_profile_opened(event: ProfileOpened) -> bytes:
    return json.dumps(
        {"display_name": event.display_name},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_profile_opened(payload: bytes) -> ProfileOpened:
    value = json.loads(payload)
    if not isinstance(value, dict) or not isinstance(value.get("display_name"), str):
        raise ValueError("invalid profile.opened payload")
    return ProfileOpened(value["display_name"])


schemas = (
    EventSchemaRegistry()
    .register(
        EventSchema(
            alias="profile.opened",
            version=1,
            event_type=ProfileOpened,
            encoder=encode_profile_opened,
            decoder=decode_profile_opened,
        )
    )
    .register(
        EventSchema(
            alias="profile.display-name-changed",
            version=1,
            event_type=DisplayNameChanged,
            encoder=lambda event: event.display_name.encode("utf-8"),
            decoder=lambda payload: DisplayNameChanged(payload.decode("utf-8")),
        )
    )
    .freeze()
)
```

Encoding looks up the exact domain-event class, validates metadata/header
limits, invokes the encoder, and returns `AppendEvent` at the current version.
Decoding looks up the persisted alias, validates limits and version, upcasts to
the current bytes shape, invokes the decoder, and verifies that the exact
registered event class was returned.

The registry rejects duplicate aliases and duplicate event classes. It also
rejects unknown aliases, future persisted versions, non-bytes codec results,
wrong decoded classes, and use before freeze. Codec and upcaster exceptions are
wrapped in typed schema errors with the original cause.

Persisted aliases must remain stable when Python modules or classes are renamed.
Aliases are never used for dynamic imports or code execution.

## Evolve a Schema with Upcasters

An upcaster transforms bytes from one schema version to the next. Suppose
historical version 1 did not contain `visibility`, while current version 2 does:

```python
@dataclass(frozen=True, slots=True)
class MemberRegistered(Event):
    handle: str
    visibility: str


def upcast_member_registered_v1(payload: bytes) -> bytes:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("member registration must be an object")
    value["visibility"] = "members"
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def decode_member_registered(payload: bytes) -> MemberRegistered:
    value = json.loads(payload)
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("handle"), str)
        or not isinstance(value.get("visibility"), str)
    ):
        raise ValueError("invalid member registration")
    return MemberRegistered(value["handle"], value["visibility"])


member_schema = EventSchema(
    alias="community.member-registered",
    version=2,
    event_type=MemberRegistered,
    encoder=lambda event: json.dumps(
        {"handle": event.handle, "visibility": event.visibility},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8"),
    decoder=decode_member_registered,
    upcasters={1: upcast_member_registered_v1},
)
```

For current version `N`, the schema declaration must provide exactly the
contiguous source-version keys `1` through `N - 1`. Decoding version 1 with a
version 3 schema runs upcaster 1, validates the returned bytes, runs upcaster 2,
validates again, and then uses the current decoder.

Upcasters should be pure deterministic bytes transformations. They must not
execute aggregate behavior, perform I/O, resolve providers, publish events, or
depend on current mutable state. The decoder validates the final payload shape.

A future stored version is rejected rather than guessed. Missing or failing
upcast steps are typed failures. Upcasting does not rewrite stored history; it
adapts representation during reads.

## Resource Limits

`EventSourcingLimits` provides finite defaults shared by schemas, stores, and
repositories:

| Limit | Default |
| --- | ---: |
| `max_payload_bytes` | 1,048,576 |
| `max_headers` | 64 |
| `max_header_name_bytes` | 256 |
| `max_header_value_bytes` | 4,096 |
| `max_upcast_steps` | 32 |
| `read_page_size` | 500 |
| `max_events_per_append` | 1,000 |
| `max_events_per_transaction` | 10,000 |
| `max_transaction_bytes` | 16,777,216 |

Configure one limits value before constructing the registry and store:

```python
from tori_py_cqrs_event_sourcing_core import (
    EventSchemaRegistry,
    EventSourcingLimits,
    InMemoryEventStore,
)


limits = EventSourcingLimits(
    max_payload_bytes=64_000,
    read_page_size=100,
    max_events_per_transaction=500,
)
schemas = EventSchemaRegistry(limits=limits)
store = InMemoryEventStore(limits=limits)
```

Every limit must be a positive non-boolean integer. The schema registry enforces
payload, header, and upcast limits. Event stores enforce read, append,
transaction count, and transaction byte limits. A repository page size must be
positive and no greater than its schema registry's `read_page_size`.

Format-specific decoders remain responsible for shape, nesting, and complexity
limits beyond these byte-level boundaries.

## Aggregate Design Checklist

- Keep one aggregate stream as the consistency boundary for invariants that must
  conflict together.
- Validate intent in domain methods before recording an event.
- Make events immutable facts and keep `_apply()` exhaustive.
- Keep `_apply()` deterministic, synchronous, and side-effect-free.
- Treat any apply/replay exception as requiring aggregate discard and reload.
- Use stable stream categories, ID encoders, event aliases, and schema versions.
- Preserve all historical decoder/upcaster paths required by retained data.
- Keep sensitive-data minimization and erasure policy explicit; event history is
  immutable by design.
- Never publish from the aggregate. Persistence and transport delivery are
  separate application boundaries.
