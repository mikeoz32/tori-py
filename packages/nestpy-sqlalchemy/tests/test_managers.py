import asyncio
from pathlib import Path

import pytest
from nestpy_sqlalchemy import EntityManager, TransactionContextError
from sqlalchemy import String, func, select, update
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Item(Base):
    __tablename__ = "manager_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)


async def _create_manager(
    database: Path,
    *,
    autoflush: bool = False,
) -> tuple[AsyncEngine, EntityManager]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database.as_posix()}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    manager = EntityManager(
        async_sessionmaker(
            engine,
            expire_on_commit=False,
            autoflush=autoflush,
            autobegin=False,
        )
    )
    return engine, manager


@pytest.mark.asyncio
async def test_entity_operations_auto_scope_and_reuse_lexical_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, entities = await _create_manager(
        tmp_path / "operations.db",
        autoflush=True,
    )
    original_begin_nested = AsyncSession.begin_nested
    original_refresh = AsyncSession.refresh
    savepoint_calls = 0
    refresh_autoflush: list[bool] = []

    def begin_nested(session: AsyncSession):
        nonlocal savepoint_calls
        savepoint_calls += 1
        return original_begin_nested(session)

    async def refresh(session: AsyncSession, *args, **kwargs) -> None:
        refresh_autoflush.append(session.autoflush)
        await original_refresh(session, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "begin_nested", begin_nested)
    monkeypatch.setattr(AsyncSession, "refresh", refresh)
    try:
        first = await entities.add(Item(name="first"))
        second, third = await entities.add_all(
            (Item(name="second"), Item(name="third"))
        )
        assert (first.id, second.id, third.id) == (1, 2, 3)
        assert await entities.get_one(Item, first.id) is not first
        with pytest.raises(NoResultFound):
            await entities.get_one(Item, 999)
        assert await entities.scalar(select(func.count()).select_from(Item)) == 3
        await entities.execute(
            update(Item).where(Item.id == first.id).values(name="updated")
        )
        await entities.refresh(first)
        assert first.name == "updated"
        with pytest.raises(TransactionContextError, match="active transaction"):
            await entities.flush()

        async with entities.transaction() as transaction:
            assert transaction is entities
            loaded = await transaction.get_one(Item, second.id)
            assert await transaction.get(Item, second.id) is loaded
            await transaction.refresh(loaded)
            loaded.name = "inside"
            await transaction.flush()
            assert await transaction.scalar(select(func.count()).select_from(Item)) == 3
        assert savepoint_calls == 0
        assert refresh_autoflush == [False, True]

        detached = await entities.get_one(Item, first.id)
        detached.name = "merged"
        merged = await entities.merge(detached)
        assert merged.name == "merged"
        await entities.delete(merged)
        assert await entities.get(Item, first.id) is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_nested_scope_uses_savepoint_and_outer_transaction_continues(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_manager(tmp_path / "savepoint.db")
    try:
        async with entities.transaction() as outer:
            await entities.add(Item(name="before"))
            with pytest.raises(RuntimeError, match="rollback savepoint"):
                async with entities.transaction() as nested:
                    assert nested is outer is entities
                    await entities.add(Item(name="rolled-back"))
                    raise RuntimeError("rollback savepoint")
            await entities.add(Item(name="after"))

        rows = await entities.scalars(select(Item).order_by(Item.id))
        assert [item.name for item in rows] == ["before", "after"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_outer_rollback_includes_successful_nested_savepoint(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_manager(tmp_path / "outer-rollback.db")
    try:
        with pytest.raises(RuntimeError, match="rollback outer"):
            async with entities.transaction():
                await entities.add(Item(name="outer"))
                async with entities.transaction():
                    await entities.add(Item(name="nested"))
                raise RuntimeError("rollback outer")

        assert await entities.scalar(select(func.count()).select_from(Item)) == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_integrity_failure_rolls_back_and_clears_context(tmp_path: Path) -> None:
    engine, entities = await _create_manager(tmp_path / "integrity.db")
    try:
        await entities.add(Item(name="unique"))
        with pytest.raises(IntegrityError):
            await entities.add(Item(name="unique"))
        assert await entities.scalar(select(func.count()).select_from(Item)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_child_task_cannot_use_inherited_transaction_context(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_manager(tmp_path / "child-task.db")
    release = asyncio.Event()

    async def child_operation() -> None:
        await release.wait()
        await entities.scalar(select(1))

    try:
        async with entities.transaction():
            child = asyncio.create_task(child_operation())
            release.set()
            with pytest.raises(TransactionContextError, match="child task"):
                await child
            assert await entities.scalar(select(1)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_child_task_cannot_use_context_after_parent_transaction_exits(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_manager(tmp_path / "escaped-child.db")
    release = asyncio.Event()

    async def escaped_operation() -> None:
        await release.wait()
        await entities.scalar(select(1))

    try:
        async with entities.transaction():
            child = asyncio.create_task(escaped_operation())
        release.set()
        with pytest.raises(TransactionContextError, match="no longer active"):
            await child
        assert await entities.scalar(select(1)) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_parallel_top_level_tasks_receive_distinct_sessions(
    tmp_path: Path,
) -> None:
    engine, entities = await _create_manager(tmp_path / "concurrent.db")
    barrier = asyncio.Event()
    entered = 0

    async def session_identity() -> int:
        nonlocal entered
        async with entities.transaction():
            identity = id(entities._require_session())
            entered += 1
            if entered == 12:
                barrier.set()
            await barrier.wait()
            assert await entities.scalar(select(1)) == 1
            return identity

    try:
        identities = await asyncio.gather(*(session_identity() for _ in range(12)))
        assert len(set(identities)) == len(identities)
    finally:
        await engine.dispose()
