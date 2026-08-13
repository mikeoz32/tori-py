# Event-Sourced Community Project

This larger reference project combines `tori-py-cqrs-core`, `tori-py-cqrs-event-sourcing-core`,
`tori-py-cqrs`, `tori-py-cqrs-event-sourcing`, and ToriPy HTTP/testing in one
layered application.

It models members, groups, and posts rather than a toy counter:

- profile visibility and suspension are aggregate state;
- public groups admit immediately; private groups require moderator review;
- posting requires active group membership;
- post hiding requires group moderator authority;
- post bodies live in an erasable `ContentVault`, while immutable events contain
  only content references;
- HTTP bearer credentials are resolved by a guard into trusted request-state
  principals; controllers never accept actor IDs as identity claims;
- a checkpointed projection reads committed events in global-position order and
  applies viewer-specific privacy filtering.

## Layout

```text
event_sourcing/
    domain/             Member, Group, Post aggregates and domain policy
    application/        Commands, queries, handlers, projection, DTOs
    infrastructure/     Schemas, repositories, ID source, content vault
    api.py               HTTP adapter and Problem Details filter
    app.py               ToriPy composition root
    test_event_sourcing_project.py
```

## Write Path

Every command handler uses the request-scoped `@command_handler()` shorthand,
opts into `@use_event_sourcing()`, and injects decorated repository classes. The
integration owns a private Unit of Work in
the fresh CQRS handler scope, intentionally separate from the surrounding HTTP
request scope:

1. Repositories load streams from one repeatable transaction snapshot.
2. Aggregates enforce actor, privacy, membership, and moderation invariants.
3. Repositories stage events at exact expected versions.
4. The handler returns a response candidate without transaction plumbing.
5. The outer interceptor atomically commits all staged streams.
6. ToriPy returns the candidate only after confirmed commit and scope cleanup.

`AppModule` imports the keyed global event-sourcing root once. `CommunityModule`
imports only its repository feature descriptor, which selects that infrastructure
with `root_key="community"`; the feature does not receive or import the root.

Handlers never inject `EventSourcingUnitOfWork` or call `commit()`. The post
handler registers content erasure through `CommandSynchronization`; compensation
runs only for a confirmed non-commit, never for an indeterminate outcome.

Projection catch-up belongs to queries, not write success. A projection failure
therefore cannot turn a confirmed command into an apparent rollback or cause
content compensation after commit.

The stale-writer test opens two snapshots and proves that one writer is faulted by
optimistic concurrency instead of overwriting another decision.

## Evolution

`community.member-registered` is schema version 2. The tests insert a historical
version-1 payload without `visibility`; the registered upcaster supplies
`members` visibility before decode and aggregate replay. Persisted aliases never
use Python class paths.

## Privacy

The HTTP adapter derives actor IDs from bearer credentials in a guard and then
places the trusted ID explicitly into commands. Direct bus callers are trusted
application adapters and must provide an authenticated actor. Visibility and
group access checks exist in domain/projection code, not only controllers.
Inaccessible private resources use generic 404 responses, rosters are visible
only to moderators, and pending membership responses disclose only group ID and
status. Hidden posts disappear for ordinary members; moderators see title and
moderation reason, but not the hidden body.

Raw post bodies are deliberately excluded from immutable event streams. The
example vault demonstrates an erasure boundary, but it is process-local and not
transactionally coordinated with EventStore. Production needs encrypted content
storage, authorization/audit policy, retention jobs, and transactional or
compensating coordination.

Body erasure does not remove every potentially sensitive event field. Handles,
display names, titles, suspension reasons, rejection reasons, and moderation
reasons remain immutable history in this example. A production schema needs a
data-classification and minimization policy before persistence.

## Guarantees

The projection keeps an in-memory global-position checkpoint and catches up from
later committed store positions rather than relying on fire-and-forget `EventBus`
delivery. It is not a durable production projector: checkpoint/read-model state
disappears on restart, poison-event policy is absent, and `InMemoryEventStore` is
non-durable. PostgreSQL/outbox/projector adapters remain future work.

The projector processes a finite page budget per query and fails closed with a
temporary-unavailable response if it cannot reach the committed feed head. Post
listing uses separate sorted visible/all indexes, so cursor lookup and response
construction are bounded by the requested limit. Commands are not idempotent:
clients must not blindly retry register/create/publish after a timeout or
indeterminate commit. Production needs stable command IDs and a persisted
idempotency/inbox contract.

Cross-aggregate authorization uses the repeatable snapshot seen by the command.
A concurrent suspension or role revocation does not conflict with a post-only
append. Strong revocation semantics require a shared policy stream, read-version
preconditions, or another transactionally validated authorization record.

`CredentialStore`, `PlatformPolicy`, and generated bearer tokens are educational
in-process adapters, not production authentication. Real deployments need hashed
credential storage, expiry/rotation, rate limiting, revocation, and audited
administrator assignment.

## Run

```text
uv run pytest examples/tori_py/cqrs/event_sourcing -q
uv run uvicorn examples.tori_py.cqrs.event_sourcing.app:application
```
