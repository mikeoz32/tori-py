import asyncio
from pathlib import Path

import pytest
from nestpy_sqlalchemy import EntityManager, EntityTransaction, SessionManager
from sqlalchemy import String, func, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "manager_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


async def _create_managers(
    database: Path,
) -> tuple[AsyncEngine, SessionManager, EntityManager]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        autoflush=False,
        autobegin=False,
    )
    sessions = SessionManager(factory)
    return engine, sessions, EntityManager(sessions)


@pytest.mark.asyncio
async def test_one_shot_entity_operations_commit_and_return_detached_values(
    tmp_path: Path,
) -> None:
    engine, _, entities = await _create_managers(tmp_path / "operations.db")
    try:
        first = await entities.add(Item(name="first"))
        second, third = await entities.add_all(
            (Item(name="second"), Item(name="third"))
        )
        assert (first.id, second.id, third.id) == (1, 2, 3)

        loaded = await entities.get(Item, first.id)
        assert loaded is not None
        assert loaded.name == "first"
        assert await entities.get_one(Item, second.id)
        with pytest.raises(NoResultFound):
            await entities.get_one(Item, 999)

        result = await entities.scalars(select(Item).order_by(Item.id))
        assert [item.name for item in result] == ["first", "second", "third"]
        assert await entities.scalar(select(func.count()).select_from(Item)) == 3

        await entities.execute(
            update(Item).where(Item.id == first.id).values(name="updated")
        )
        updated = await entities.get_one(Item, first.id)
        assert updated.name == "updated"

        updated.name = "merged"
        merged = await entities.merge(updated)
        assert merged.name == "merged"
        await entities.delete(merged)
        assert await entities.get(Item, first.id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bound_transaction_shares_identity_and_rolls_back_as_one_unit(
    tmp_path: Path,
) -> None:
    engine, _, entities = await _create_managers(tmp_path / "rollback.db")
    failure = RuntimeError("abort transaction")
    try:
        with pytest.raises(RuntimeError, match="abort transaction") as captured:
            async with entities.transaction() as transaction:
                assert isinstance(transaction, EntityTransaction)
                item = transaction.add(Item(name="temporary"))
                await transaction.flush((item,))
                assert await transaction.get(Item, item.id) is item
                assert not hasattr(transaction, "commit")
                assert not hasattr(transaction, "rollback")
                assert not hasattr(transaction, "close")
                raise failure
        assert captured.value is failure
        assert await entities.scalar(select(func.count()).select_from(Item)) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_one_shot_integrity_error_rolls_back_and_closes_session(
    tmp_path: Path,
) -> None:
    engine, _, entities = await _create_managers(tmp_path / "integrity.db")
    try:
        await entities.add(Item(name="unique"))
        with pytest.raises(IntegrityError):
            await entities.add(Item(name="unique"))
        assert await entities.scalar(select(func.count()).select_from(Item)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_singleton_session_manager_opens_distinct_concurrent_sessions(
    tmp_path: Path,
) -> None:
    engine, sessions, _ = await _create_managers(tmp_path / "concurrent.db")

    async def session_identity() -> int:
        async with sessions.transaction() as session:
            await asyncio.sleep(0)
            return id(session)

    try:
        identities = await asyncio.gather(*(session_identity() for _ in range(12)))
        assert len(set(identities)) == len(identities)

        async with sessions.session() as session:
            assert not session.in_transaction()
            async with session.begin():
                assert await session.scalar(select(1)) == 1
    finally:
        await engine.dispose()
