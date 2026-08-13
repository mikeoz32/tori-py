"""Singleton entity manager over guarded task-local SQLAlchemy transactions."""

import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager, nullcontext
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Self, cast

from sqlalchemy import Executable
from sqlalchemy.engine import Result, ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tori_py_sqlalchemy.errors import TransactionContextError

type ExecuteParams = Mapping[str, object] | Sequence[Mapping[str, object]] | None


@dataclass(slots=True)
class _TransactionState:
    session: AsyncSession
    owner_task: asyncio.Task[Any]
    active: bool = True


class EntityManager:
    """Auto-scope operations and own explicit contextual transactions."""

    __slots__ = ("_current", "_factory")

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self._current: ContextVar[_TransactionState | None] = ContextVar(
            f"tori_py_sqlalchemy_transaction_{id(self):x}",
            default=None,
        )

    def transaction(self) -> AbstractAsyncContextManager[Self]:
        """Open a top-level transaction or a same-task nested savepoint."""

        return self._transaction()

    @asynccontextmanager
    async def _transaction(self):
        current = self._current.get()
        if current is not None:
            self._validate_state(current)
            async with current.session.begin_nested():
                yield self
            return

        owner_task = asyncio.current_task()
        if owner_task is None:
            raise TransactionContextError(
                "transaction must be opened from an asyncio task"
            )
        # Keep session cleanup outside transaction finalization so close still runs
        # when the database raises while committing or rolling back.
        async with self._factory() as session:
            async with session.begin():
                state = _TransactionState(session, owner_task)
                token = self._current.set(state)
                try:
                    yield self
                finally:
                    state.active = False
                    self._current.reset(token)

    async def add[EntityT](self, entity: EntityT) -> EntityT:
        """Add and flush one entity in the current or an automatic transaction."""

        async with self._operation() as session:
            session.add(entity)
            await self.flush()
        return entity

    async def add_all[EntityT](
        self,
        entities: Iterable[EntityT],
    ) -> tuple[EntityT, ...]:
        """Add and flush entities in the current or an automatic transaction."""

        values = tuple(entities)
        async with self._operation() as session:
            session.add_all(values)
            await self.flush()
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
        """Load one entity by primary key in the current or an automatic scope."""

        self._require_explicit_lock_scope(with_for_update)
        async with self._operation() as session:
            return await session.get(
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

        self._require_explicit_lock_scope(with_for_update)
        async with self._operation() as session:
            return await session.get_one(
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
        """Merge and flush detached state in the current or automatic transaction."""

        async with self._operation() as session:
            merged = await session.merge(entity, load=load, options=options)
            await self.flush()
            return merged

    async def delete(self, entity: object) -> None:
        """Delete and flush one entity in the current or automatic transaction."""

        async with self._operation() as session:
            await session.delete(entity)
            await self.flush()

    async def flush(self, entities: Sequence[object] | None = None) -> None:
        """Flush pending changes without finalizing the active transaction."""

        await self._require_session().flush(entities)

    async def refresh(
        self,
        entity: object,
        *,
        attribute_names: Iterable[str] | None = None,
        with_for_update: bool = False,
    ) -> None:
        """Refresh attributes in the current or an automatic transaction."""

        self._require_explicit_lock_scope(with_for_update)
        standalone = self._current.get() is None
        async with self._operation() as session:
            if standalone:
                session.add(entity)
            try:
                autoflush_guard = session.no_autoflush if standalone else nullcontext()
                with autoflush_guard:
                    await session.refresh(
                        entity,
                        attribute_names=attribute_names,
                        with_for_update=with_for_update,
                    )
            finally:
                if standalone:
                    session.expunge_all()

    async def execute(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Result[Any]:
        """Execute a buffered statement in the current or automatic transaction."""

        async with self._operation() as session:
            return await session.execute(statement, params=cast(Any, params))

    async def scalar(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Any:
        """Execute a statement and return its first scalar value."""

        async with self._operation() as session:
            return await session.scalar(statement, params=cast(Any, params))

    async def scalars(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> ScalarResult[Any]:
        """Execute a statement and return its buffered scalar result."""

        async with self._operation() as session:
            return await session.scalars(statement, params=cast(Any, params))

    @asynccontextmanager
    async def _operation(self) -> AsyncIterator[AsyncSession]:
        state = self._current.get()
        if state is not None:
            self._validate_state(state)
            yield state.session
            return

        async with self.transaction():
            yield self._require_session()

    def _require_explicit_lock_scope(self, with_for_update: bool) -> None:
        if with_for_update and self._current.get() is None:
            raise TransactionContextError(
                "with_for_update requires an explicit transaction"
            )

    def _require_session(self) -> AsyncSession:
        state = self._current.get()
        if state is None or not state.active:
            raise TransactionContextError(
                "entity operation requires an active transaction"
            )
        self._validate_state(state)
        return state.session

    @staticmethod
    def _validate_state(state: _TransactionState) -> None:
        if not state.active:
            raise TransactionContextError("transaction context is no longer active")
        if state.owner_task is not asyncio.current_task():
            raise TransactionContextError(
                "transaction context cannot be used from a child task"
            )


__all__ = ["EntityManager", "ExecuteParams"]
