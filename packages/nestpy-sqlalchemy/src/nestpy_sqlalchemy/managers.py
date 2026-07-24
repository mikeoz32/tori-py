"""Singleton session and entity managers over short-lived AsyncSession values."""

from collections.abc import Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, cast

from sqlalchemy import Executable
from sqlalchemy.engine import Result, ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

type ExecuteParams = Mapping[str, object] | Sequence[Mapping[str, object]] | None


class SessionManager:
    """Open short-lived sessions and transactions from one singleton factory."""

    __slots__ = ("_factory",)

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    def session(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Open and always close one session without starting a transaction."""

        return self._factory()

    def transaction(self) -> AbstractAsyncContextManager[AsyncSession]:
        """Open a session and commit, rollback, and close it automatically."""

        return self._transaction()

    @asynccontextmanager
    async def _transaction(self):
        # Keep session cleanup outside transaction finalization so close still runs
        # when the database raises while committing or rolling back.
        async with self._factory() as session:
            async with session.begin():
                yield session


class EntityTransaction:
    """Entity operations bound to one manager-owned transaction."""

    __slots__ = ("_session",)

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add[EntityT](self, entity: EntityT) -> EntityT:
        """Add one entity to the current Unit of Work without flushing."""

        self._session.add(entity)
        return entity

    def add_all[EntityT](self, entities: Iterable[EntityT]) -> tuple[EntityT, ...]:
        """Add entities to the current Unit of Work without flushing."""

        values = tuple(entities)
        self._session.add_all(values)
        return values

    async def get[EntityT](
        self,
        entity_type: type[EntityT],
        identity: object,
        *,
        options: Sequence[Any] = (),
        populate_existing: bool = False,
        with_for_update: bool = False,
    ) -> EntityT | None:
        """Load one entity by primary key from the transaction identity map."""

        return await self._session.get(
            entity_type,
            cast(Any, identity),
            options=options,
            populate_existing=populate_existing,
            with_for_update=with_for_update,
        )

    async def get_one[EntityT](
        self,
        entity_type: type[EntityT],
        identity: object,
        *,
        options: Sequence[Any] = (),
        populate_existing: bool = False,
        with_for_update: bool = False,
    ) -> EntityT:
        """Load one entity by primary key or raise SQLAlchemy's no-result error."""

        return await self._session.get_one(
            entity_type,
            cast(Any, identity),
            options=options,
            populate_existing=populate_existing,
            with_for_update=with_for_update,
        )

    async def merge[EntityT](
        self,
        entity: EntityT,
        *,
        load: bool = True,
        options: Sequence[Any] = (),
    ) -> EntityT:
        """Merge detached state into the current transaction."""

        return await self._session.merge(entity, load=load, options=options)

    async def delete(self, entity: object) -> None:
        """Mark one entity for deletion in the current transaction."""

        await self._session.delete(entity)

    async def flush(self, entities: Sequence[object] | None = None) -> None:
        """Flush pending changes without committing the transaction."""

        await self._session.flush(entities)

    async def refresh(
        self,
        entity: object,
        *,
        attribute_names: Iterable[str] | None = None,
        with_for_update: bool = False,
    ) -> None:
        """Refresh attributes of a persistent entity."""

        await self._session.refresh(
            entity,
            attribute_names=attribute_names,
            with_for_update=with_for_update,
        )

    async def execute(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Result[Any]:
        """Execute one buffered SQLAlchemy statement in the transaction."""

        return await self._session.execute(statement, params=cast(Any, params))

    async def scalar(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Any:
        """Execute a statement and return its first scalar value."""

        return await self._session.scalar(statement, params=cast(Any, params))

    async def scalars(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> ScalarResult[Any]:
        """Execute a statement and return its buffered scalar result."""

        return await self._session.scalars(statement, params=cast(Any, params))


class EntityManager:
    """Singleton gateway for auto-scoped SQLAlchemy entity operations."""

    __slots__ = ("_sessions",)

    def __init__(self, sessions: SessionManager) -> None:
        self._sessions = sessions

    def transaction(self) -> AbstractAsyncContextManager[EntityTransaction]:
        """Open one transaction-bound entity manager."""

        return self._transaction()

    @asynccontextmanager
    async def _transaction(self):
        async with self._sessions.transaction() as session:
            yield EntityTransaction(session)

    async def add[EntityT](self, entity: EntityT) -> EntityT:
        """Add, flush, and commit one entity in a new transaction."""

        async with self.transaction() as transaction:
            transaction.add(entity)
            await transaction.flush()
        return entity

    async def add_all[EntityT](
        self,
        entities: Iterable[EntityT],
    ) -> tuple[EntityT, ...]:
        """Add, flush, and commit entities in one new transaction."""

        async with self.transaction() as transaction:
            values = transaction.add_all(entities)
            await transaction.flush()
        return values

    async def get[EntityT](
        self,
        entity_type: type[EntityT],
        identity: object,
        *,
        options: Sequence[Any] = (),
        populate_existing: bool = False,
    ) -> EntityT | None:
        """Load one entity by primary key in an automatically closed transaction."""

        async with self.transaction() as transaction:
            return await transaction.get(
                entity_type,
                identity,
                options=options,
                populate_existing=populate_existing,
            )

    async def get_one[EntityT](
        self,
        entity_type: type[EntityT],
        identity: object,
        *,
        options: Sequence[Any] = (),
        populate_existing: bool = False,
    ) -> EntityT:
        """Load one entity or propagate SQLAlchemy's no-result error."""

        async with self.transaction() as transaction:
            return await transaction.get_one(
                entity_type,
                identity,
                options=options,
                populate_existing=populate_existing,
            )

    async def merge[EntityT](
        self,
        entity: EntityT,
        *,
        load: bool = True,
        options: Sequence[Any] = (),
    ) -> EntityT:
        """Merge, flush, and commit detached entity state."""

        async with self.transaction() as transaction:
            merged = await transaction.merge(entity, load=load, options=options)
            await transaction.flush()
            return merged

    async def delete(self, entity: object) -> None:
        """Delete and commit one entity in a new transaction."""

        async with self.transaction() as transaction:
            await transaction.delete(entity)
            await transaction.flush()

    async def execute(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Result[Any]:
        """Execute and commit one buffered statement in a new transaction."""

        async with self.transaction() as transaction:
            return await transaction.execute(statement, params)

    async def scalar(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Any:
        """Execute a statement and return its first scalar value."""

        async with self.transaction() as transaction:
            return await transaction.scalar(statement, params)

    async def scalars(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> ScalarResult[Any]:
        """Execute a statement and return its buffered scalar result."""

        async with self.transaction() as transaction:
            return await transaction.scalars(statement, params)


__all__ = ["EntityManager", "EntityTransaction", "ExecuteParams", "SessionManager"]
