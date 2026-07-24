from pathlib import Path
from typing import Any, cast

import pytest
from nestpy_sqlalchemy import (
    EntityManager,
    Repository,
    RepositoryBindingError,
    SessionManager,
    SqlAlchemyConfigurationError,
    get_repository_token,
    inject_repository,
    repository,
)
from sqlalchemy import ForeignKey, String, event, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.exc import MultipleResultsFound, NoResultFound
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    joinedload,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "repository_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str] = mapped_column(String(40))


class OtherItem(Base):
    __tablename__ = "repository_other_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


class Group(Base):
    __tablename__ = "repository_groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80))
    members: Mapped[list[GroupMember]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
    )


class GroupMember(Base):
    __tablename__ = "repository_group_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("repository_groups.id"))
    name: Mapped[str] = mapped_column(String(80))
    group: Mapped[Group] = relationship(back_populates="members")


class CollisionBaseOne(DeclarativeBase):
    pass


class CollisionOne(CollisionBaseOne):
    __tablename__ = "collision_one"

    id: Mapped[int] = mapped_column(primary_key=True)


class CollisionBaseTwo(DeclarativeBase):
    pass


class CollisionTwo(CollisionBaseTwo):
    __tablename__ = "collision_two"

    id: Mapped[int] = mapped_column(primary_key=True)


CollisionOne.__module__ = "tests.collision_models"
CollisionOne.__qualname__ = "Duplicate"
CollisionTwo.__module__ = "tests.collision_models"
CollisionTwo.__qualname__ = "Duplicate"


@repository(Item)
class ItemRepository(Repository[Item]):
    async def find_named(self, prefix: str) -> tuple[Item, ...]:
        rows = await self._scalars(
            select(Item).where(Item.name.startswith(prefix)).order_by(Item.id)
        )
        return tuple(rows)


async def _create_managers(
    database: Path,
) -> tuple[AsyncEngine, EntityManager]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = SessionManager(
        async_sessionmaker(
            engine,
            expire_on_commit=False,
            autoflush=False,
            autobegin=False,
        )
    )
    return engine, EntityManager(sessions)


@pytest.mark.asyncio
async def test_default_repository_crud_and_native_expression_queries(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_managers(tmp_path / "repository.db")
    items = entities.repository(Item)
    try:
        assert isinstance(items, Repository)
        assert items.entity_type is Item
        alpha, beta, gamma = await items.add_all(
            (
                Item(name="alpha", category="one"),
                Item(name="beta", category="one"),
                Item(name="gamma", category="two"),
            )
        )
        assert (alpha.id, beta.id, gamma.id) == (1, 2, 3)
        assert len(await items.find(order_by=(Item.id,))) == 3
        assert len(await items.find(order_by=(Item.id,), limit=3)) == 3
        assert (await items.get_one(alpha.id)).name == "alpha"
        assert sa_inspect(await items.get_one(alpha.id)).detached
        assert await items.get(999) is None

        found = await items.find(
            Item.category == "one",
            order_by=(Item.name.desc(),),
            offset=1,
            limit=1,
        )
        assert [item.name for item in found] == ["alpha"]
        assert (await items.find_one(Item.name == "beta")) is not None
        assert await items.find_one(Item.name == "missing") is None
        assert (await items.find_one_or_raise(Item.name == "gamma")).id == gamma.id
        with pytest.raises(NoResultFound):
            await items.find_one_or_raise(Item.name == "missing")
        with pytest.raises(MultipleResultsFound):
            await items.find_one(Item.category == "one")
        with pytest.raises(MultipleResultsFound):
            await items.find_one_or_raise(Item.category == "one")
        assert await items.count() == 3
        assert await items.count(Item.category == "one") == 2
        assert await items.exists(Item.name == "alpha")
        assert not await items.exists(Item.name == "missing")

        beta.name = "renamed"
        merged = await items.merge(beta)
        assert merged.name == "renamed"
        await items.delete(merged)
        assert await items.count() == 2

        groups = entities.repository(Group)
        created_group = await groups.add(
            Group(
                name="maintainers",
                members=[GroupMember(name="Ada"), GroupMember(name="Grace")],
            )
        )
        loaded_group = await groups.find_one_or_raise(
            Group.id == created_group.id,
            options=(joinedload(Group.members),),
        )
        assert sa_inspect(loaded_group).detached
        assert [member.name for member in loaded_group.members] == ["Ada", "Grace"]
        optional_group = await groups.find_one(
            Group.id == created_group.id,
            options=(joinedload(Group.members),),
        )
        assert optional_group is not None
        assert [member.name for member in optional_group.members] == ["Ada", "Grace"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_custom_repository_and_explicit_binding_share_one_transaction(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_managers(tmp_path / "binding.db")
    custom = ItemRepository(Item, entities)
    failure = RuntimeError("abort repository transaction")
    try:
        await custom.add(Item(name="outside", category="stable"))
        with pytest.raises(RuntimeError, match="abort repository transaction"):
            async with entities.transaction() as transaction:
                bound = custom.bind(transaction)
                default_bound = transaction.repository(Item)
                assert isinstance(bound, ItemRepository)
                assert bound is not custom
                created = await bound.add(Item(name="inside", category="temporary"))
                assert await default_bound.get(created.id) is created
                assert await bound.get(created.id, with_for_update=True) is created
                assert (
                    await bound.find_one(
                        Item.id == created.id,
                        with_for_update=True,
                    )
                    is created
                )
                assert await bound.count(Item.category == "temporary") == 1
                assert await bound.exists(Item.name == "inside")
                assert [item.name for item in await bound.find_named("in")] == [
                    "inside"
                ]
                raise failure
        assert [item.name for item in await custom.find()] == ["outside"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_repository_binding_rejects_inactive_and_wrong_root_transactions(
    tmp_path: Path,
) -> None:
    first_engine, first_entities = await _create_managers(tmp_path / "first.db")
    second_engine, second_entities = await _create_managers(tmp_path / "second.db")
    repository_ = first_entities.repository(Item)
    try:
        async with second_entities.transaction() as wrong_transaction:
            with pytest.raises(RepositoryBindingError, match="different"):
                repository_.bind(wrong_transaction)

        async with first_entities.transaction() as transaction:
            bound = repository_.bind(transaction)
        with pytest.raises(RepositoryBindingError, match="no longer active"):
            repository_.bind(transaction)
        with pytest.raises(RepositoryBindingError, match="no longer active"):
            await bound.count()
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


@pytest.mark.asyncio
async def test_repository_validates_entities_pagination_and_lock_lifetime(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_managers(tmp_path / "validation.db")
    items = entities.repository(Item)
    try:
        with pytest.raises(TypeError, match="Item entities"):
            await items.add(cast(Any, OtherItem()))
        for arguments in ({"offset": -1}, {"offset": True}, {"limit": 0}):
            with pytest.raises(ValueError):
                await items.find(**cast(Any, arguments))
        with pytest.raises(RepositoryBindingError, match="transaction-bound"):
            await items.get(1, with_for_update=True)
        with pytest.raises(RepositoryBindingError, match="transaction-bound"):
            await items.find_one(with_for_update=True)
    finally:
        await engine.dispose()


def test_repository_declaration_requires_mapped_class_and_inherited_constructor() -> (
    None
):
    class Unmapped:
        pass

    with pytest.raises(SqlAlchemyConfigurationError, match="mapped"):
        repository(Unmapped)

    with pytest.raises(SqlAlchemyConfigurationError, match="constructor"):

        @repository(Item)
        class InvalidRepository(Repository[Item]):
            def __init__(self, entity_type, operations) -> None:
                super().__init__(entity_type, operations)

    class InvalidBase(Repository[Item]):
        def __init__(self, dependency: object) -> None:
            del dependency

    with pytest.raises(SqlAlchemyConfigurationError, match="constructor"):

        @repository(Item)
        class InheritedInvalidRepository(InvalidBase):
            pass

    with pytest.raises(SqlAlchemyConfigurationError, match="specialize"):

        @repository(Item)
        class WrongEntityRepository(Repository[OtherItem]):
            pass


def test_repository_tokens_use_mapped_class_identity() -> None:
    first = get_repository_token(CollisionOne)
    second = get_repository_token(CollisionTwo)
    assert CollisionOne.__module__ == CollisionTwo.__module__
    assert CollisionOne.__qualname__ == CollisionTwo.__qualname__
    assert first != second
    assert get_repository_token(CollisionOne) == first

    class Unmapped:
        pass

    with pytest.raises(SqlAlchemyConfigurationError, match="mapped"):
        get_repository_token(Unmapped)
    with pytest.raises(SqlAlchemyConfigurationError, match="mapped"):
        inject_repository(Unmapped)


@pytest.mark.asyncio
async def test_single_result_queries_apply_a_two_row_limit(tmp_path: Path) -> None:
    engine, entities = await _create_managers(tmp_path / "single-result.db")
    items = entities.repository(Item)
    executions: list[tuple[str, object]] = []

    def capture_statement(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, context, executemany
        executions.append((statement, parameters))

    event.listen(engine.sync_engine, "before_cursor_execute", capture_statement)
    try:
        await items.add_all(
            tuple(Item(name=f"item-{index}", category="many") for index in range(20))
        )
        with pytest.raises(MultipleResultsFound):
            await items.find_one(Item.category == "many")
        with pytest.raises(MultipleResultsFound):
            await items.find_one_or_raise(Item.category == "many")
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture_statement)
        await engine.dispose()

    matching_selects = [
        (statement, parameters)
        for statement, parameters in executions
        if "SELECT" in statement.upper() and "repository_items" in statement
    ]
    assert len(matching_selects) >= 2
    for statement, parameters in matching_selects[-2:]:
        assert "LIMIT" in statement.upper()
        assert isinstance(parameters, tuple)
        assert 2 in parameters
