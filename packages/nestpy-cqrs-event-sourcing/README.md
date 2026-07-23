# nestpy-cqrs-event-sourcing

`nestpy-cqrs-event-sourcing` adds explicit, opt-in event-sourced command
transactions to Nestpy CQRS applications. A decorated command receives one
fresh Unit of Work, commits automatically after its handler returns, and does
not release the handler result until synchronization and scoped cleanup finish.

```python
@aggregate_repository(Member, category="member")
class MemberRepo(EventSourcedRepository[int, Member]):
    pass


root = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(store=InMemoryEventStore, schemas=schemas),
    imports=[PersistenceModule],
    key="community",
)
feature = CqrsEventSourcingModule.for_feature(
    [MemberRepo],
    root_key="community",
)


@use_event_sourcing(key="community")
@command_handler(CreateMember, scope=Scope.REQUEST)
class CreateMemberHandler:
    def __init__(
        self,
        members: Annotated[MemberRepo, aggregate_repository(MemberRepo)],
    ) -> None:
        self.members = members


@module(imports=[feature], providers=[CreateMemberHandler])
class MembersModule:
    pass


@module(imports=[root, MembersModule])
class AppModule:
    pass
```

`for_root()` is imported once at application composition and globally exposes
only infrastructure tokens qualified by its `key`. `for_feature()` never
receives or imports that descriptor; it selects the global root with `root_key`
and creates/exports only the explicitly listed repository providers. Every
`for_feature()` call owns a fresh private module identity, so independent
submodules can register the same repository set without descriptor conflicts or
a mutable global registry.

The Unit of Work and transaction coordinator are private implementation
details, not providers available to handlers. Queries, events, and undecorated
commands do not start transactions. Persisted events are never published to
`EventBus` automatically. Use an `after_commit` callback for non-durable
in-process notification, or a transactional outbox for reliable publication.
