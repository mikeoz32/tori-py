"""ToriPy composition root for the event-sourced community project."""

from tori_py import (
    ClassProvider,
    NestApplication,
    PipelineOptions,
    ValueProvider,
    module,
)
from tori_py.http import MsgspecValidationPipe
from tori_py.starlette import StarletteAdapter, asgi
from tori_py_cqrs import CqrsModule
from tori_py_cqrs_event_sourcing import (
    CqrsEventSourcingModule,
    CqrsEventSourcingOptions,
)
from tori_py_cqrs_event_sourcing_core import (
    EventSourcingUnitOfWork,
    EventStore,
    InMemoryEventStore,
)

from examples.tori_py.cqrs.event_sourcing.api import (
    AuthenticationGuard,
    CommunityController,
    CommunityErrorFilter,
)
from examples.tori_py.cqrs.event_sourcing.application.handlers import (
    ChangeDisplayNameHandler,
    CreateGroupHandler,
    GetGroupHandler,
    GetMemberHandler,
    HidePostHandler,
    JoinGroupHandler,
    ListGroupPostsHandler,
    PublishPostHandler,
    RegisterMemberHandler,
    ReviewMembershipHandler,
    SuspendMemberHandler,
)
from examples.tori_py.cqrs.event_sourcing.application.projection import (
    CommunityProjection,
    ProjectionService,
)
from examples.tori_py.cqrs.event_sourcing.infrastructure.repositories import (
    GroupRepository,
    MemberRepository,
    PostRepository,
)
from examples.tori_py.cqrs.event_sourcing.infrastructure.schemas import build_schemas
from examples.tori_py.cqrs.event_sourcing.infrastructure.services import (
    ContentVault,
    CredentialStore,
    IdSequence,
    ObservedUnitOfWork,
    PlatformPolicy,
    UnitOfWorkMetrics,
)

metrics = UnitOfWorkMetrics()


def create_unit_of_work(
    store: EventStore,
) -> EventSourcingUnitOfWork:
    return ObservedUnitOfWork(store, metrics)


schemas = build_schemas()
cqrs_module = CqrsModule.for_root(global_=True)


@module(
    providers=[ClassProvider(InMemoryEventStore)],
    exports=[InMemoryEventStore],
)
class PersistenceModule:
    """Own the example EventStore independently from CQRS composition."""


event_sourcing_root = CqrsEventSourcingModule.for_root(
    CqrsEventSourcingOptions(
        store=InMemoryEventStore,
        schemas=schemas,
        unit_of_work_factory=create_unit_of_work,
    ),
    imports=[PersistenceModule],
    key="community",
)

event_sourcing_repositories = CqrsEventSourcingModule.for_feature(
    [MemberRepository, GroupRepository, PostRepository],
    root_key="community",
    key="community-model",
)


@module(
    imports=[
        event_sourcing_repositories,
    ],
    providers=[
        IdSequence,
        ContentVault,
        CredentialStore,
        PlatformPolicy,
        ValueProvider(UnitOfWorkMetrics, metrics),
        ClassProvider("authenticated", AuthenticationGuard),
        CommunityProjection,
        ProjectionService,
        RegisterMemberHandler,
        ChangeDisplayNameHandler,
        SuspendMemberHandler,
        CreateGroupHandler,
        JoinGroupHandler,
        ReviewMembershipHandler,
        PublishPostHandler,
        HidePostHandler,
        GetMemberHandler,
        GetGroupHandler,
        ListGroupPostsHandler,
    ],
    controllers=[CommunityController],
)
class CommunityModule:
    """Domain/application/infrastructure providers for one community context."""


@module(
    imports=[event_sourcing_root, cqrs_module, CommunityModule],
    providers=[
        ValueProvider("validation", MsgspecValidationPipe()),
        ValueProvider("community-errors", CommunityErrorFilter()),
    ],
)
class AppModule:
    """Application root exposing CQRS through the Starlette adapter."""


pipeline_options = PipelineOptions(
    pipes=("validation",),
    filters=("community-errors",),
)


async def create_application() -> NestApplication:
    return await NestApplication.create(
        AppModule,
        pipeline=pipeline_options,
        adapter=StarletteAdapter(),
    )


application = asgi(create_application)


__all__ = [
    "AppModule",
    "CommunityModule",
    "PersistenceModule",
    "application",
    "create_application",
    "pipeline_options",
]
