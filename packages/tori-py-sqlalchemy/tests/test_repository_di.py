from pathlib import Path
from typing import Annotated, Any, cast

import pytest
from sqlalchemy import String
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tori_py import BootstrapError, ClassProvider, Inject, module
from tori_py.testing import TestingModule
from tori_py_sqlalchemy import (
    EntityManager,
    Repository,
    SqlAlchemyConfigurationError,
    SqlAlchemyModule,
    get_repository_token,
    inject_repository,
    repository,
)


class Base(DeclarativeBase):
    pass


class FeatureItem(Base):
    __tablename__ = "repository_feature_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))


@repository(FeatureItem)
class FeatureItemRepository(Repository[FeatureItem]):
    pass


class RepositoryConsumer:
    def __init__(
        self,
        default: Annotated[
            Repository[FeatureItem],
            inject_repository(FeatureItem),
        ],
        custom: FeatureItemRepository,
        entities: EntityManager,
    ) -> None:
        self.default = default
        self.custom = custom
        self.entities = entities


@pytest.mark.asyncio
async def test_feature_resolves_default_and_custom_singleton_repositories() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    database = SqlAlchemyModule.for_engine(engine)
    persistence = SqlAlchemyModule.for_feature([FeatureItem, FeatureItemRepository])

    @module(
        imports=[database, persistence],
        providers=[ClassProvider(RepositoryConsumer)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        consumer = cast(
            RepositoryConsumer,
            await application.resolve(RepositoryConsumer),
        )
        default = await application.resolve(get_repository_token(FeatureItem))
        custom = await application.resolve(FeatureItemRepository)
        assert consumer.default is default
        assert consumer.custom is custom
        assert consumer.default.entity_type is FeatureItem
        assert consumer.custom.entity_type is FeatureItem
        assert consumer.default is not consumer.custom
        assert await application.resolve(RepositoryConsumer) is consumer
    finally:
        await application.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_named_feature_uses_matching_global_entity_manager() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    database = SqlAlchemyModule.for_engine(engine, key="analytics")
    persistence = SqlAlchemyModule.for_feature([FeatureItem], key="analytics")
    token = get_repository_token(FeatureItem, key="analytics")

    class AnalyticsConsumer:
        def __init__(
            self,
            items: Annotated[
                Repository[FeatureItem],
                inject_repository(FeatureItem, key="analytics"),
            ],
        ) -> None:
            self.items = items

    @module(
        imports=[database, persistence],
        providers=[ClassProvider(AnalyticsConsumer)],
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        consumer = cast(
            AnalyticsConsumer,
            await application.resolve(AnalyticsConsumer),
        )
        assert consumer.items is await application.resolve(token)
        assert consumer.items.entity_type is FeatureItem
    finally:
        await application.close()
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_features_keep_keyed_database_state_isolated(
    tmp_path: Path,
) -> None:
    default_engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'default.db').as_posix()}"
    )
    analytics_engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'analytics.db').as_posix()}"
    )
    for engine in (default_engine, analytics_engine):
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    default_database = SqlAlchemyModule.for_engine(default_engine)
    analytics_database = SqlAlchemyModule.for_engine(
        analytics_engine,
        key="analytics",
    )
    default_feature = SqlAlchemyModule.for_feature([FeatureItem])
    analytics_feature = SqlAlchemyModule.for_feature(
        [FeatureItem],
        key="analytics",
    )

    @module(
        imports=[
            default_database,
            analytics_database,
            default_feature,
            analytics_feature,
        ]
    )
    class Root:
        pass

    application = await TestingModule.create(Root).compile()
    try:
        default_items = cast(
            Repository[FeatureItem],
            await application.resolve(get_repository_token(FeatureItem)),
        )
        analytics_items = cast(
            Repository[FeatureItem],
            await application.resolve(
                get_repository_token(FeatureItem, key="analytics")
            ),
        )
        await default_items.add(FeatureItem(name="primary"))
        await analytics_items.add(FeatureItem(name="analytics"))

        assert [item.name for item in await default_items.find()] == ["primary"]
        assert [item.name for item in await analytics_items.find()] == ["analytics"]
    finally:
        await application.close()
        await default_engine.dispose()
        await analytics_engine.dispose()


@pytest.mark.asyncio
async def test_feature_cannot_resolve_an_opted_out_local_root() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    database = SqlAlchemyModule.for_engine(engine, global_=False)
    persistence = SqlAlchemyModule.for_feature([FeatureItem])

    @module(imports=[database, persistence])
    class Root:
        pass

    try:
        with pytest.raises(BootstrapError, match="entity_manager"):
            await TestingModule.create(Root).compile()
    finally:
        await engine.dispose()


def test_repository_tokens_markers_and_feature_declarations_are_exact() -> None:
    token = get_repository_token(FeatureItem, key="analytics")
    assert token == get_repository_token(FeatureItem, key="analytics")
    assert inject_repository(FeatureItem, key="analytics") == Inject(token)

    feature = SqlAlchemyModule.for_feature([FeatureItem, FeatureItemRepository])
    spec = cast(Any, feature.factory())
    providers = {provider.token: provider for provider in spec.providers}
    assert set(providers) == {
        get_repository_token(FeatureItem),
        FeatureItemRepository,
    }
    assert all(provider.manage is False for provider in providers.values())
    assert set(spec.exports) == set(providers)
    assert spec.global_ is False


def test_invalid_feature_declarations_fail_eagerly() -> None:
    class Unmapped:
        pass

    class UndecoratedRepository(Repository[FeatureItem]):
        pass

    for features, message in (
        ([], "must not be empty"),
        ([FeatureItem, FeatureItem], "duplicates"),
        ([Unmapped], "mapped"),
        ([UndecoratedRepository], "decorated"),
    ):
        with pytest.raises(SqlAlchemyConfigurationError, match=message):
            SqlAlchemyModule.for_feature(features)
    with pytest.raises(SqlAlchemyConfigurationError, match="iterable"):
        SqlAlchemyModule.for_feature(cast(Any, None))
