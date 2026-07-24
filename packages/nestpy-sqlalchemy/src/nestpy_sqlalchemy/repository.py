"""Model-bound default and custom repositories over entity managers."""

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Self, cast, get_args, get_origin

from nestpy import BootstrapError, Reflector, metadata
from sqlalchemy import (
    Executable,
    func,
    select,
)
from sqlalchemy import (
    exists as sql_exists,
)
from sqlalchemy.engine import Result, ScalarResult

from nestpy_sqlalchemy.errors import (
    RepositoryBindingError,
    SqlAlchemyConfigurationError,
)
from nestpy_sqlalchemy.managers import (
    EntityManager,
    EntityTransaction,
    ExecuteParams,
)
from nestpy_sqlalchemy.tokens import _validate_entity_type


@dataclass(frozen=True, slots=True)
class _RepositoryMetadata:
    entity_type: type[object]


_REPOSITORY = Reflector.create_decorator("nestpy_sqlalchemy.repository")
_REFLECTOR = Reflector()


class Repository[EntityT]:
    """Model-bound persistence operations over one manager or transaction."""

    __slots__ = ("_entity_type", "_manager", "_operations")

    def __init__(
        self,
        entity_type: type[EntityT],
        operations: EntityManager | EntityTransaction,
    ) -> None:
        _validate_entity_type(entity_type)
        if isinstance(operations, EntityManager):
            manager = operations
        elif isinstance(operations, EntityTransaction):
            manager = operations._repository_owner()
        else:
            raise TypeError(
                "repository operations must be an EntityManager or transaction"
            )
        self._entity_type = entity_type
        self._manager = manager
        self._operations = operations

    @property
    def entity_type(self) -> type[EntityT]:
        """Return the SQLAlchemy mapped class owned by this repository."""

        return self._entity_type

    def bind(self, transaction: EntityTransaction) -> Self:
        """Create the same concrete repository bound to one active transaction."""

        if not isinstance(transaction, EntityTransaction):
            raise TypeError("repository binding requires an EntityTransaction")
        transaction._require_repository_binding(self._manager)
        return type(self)(self._entity_type, transaction)

    async def add(self, entity: EntityT) -> EntityT:
        """Add and flush one entity, committing only for one-shot repositories."""

        self._require_entity(entity)
        transaction = self._bound_transaction()
        if transaction is None:
            return await self._manager.add(entity)
        transaction.add(entity)
        await transaction.flush()
        return entity

    async def add_all(self, entities: Sequence[EntityT]) -> tuple[EntityT, ...]:
        """Add and flush entities in the repository's operation boundary."""

        values = tuple(entities)
        for entity in values:
            self._require_entity(entity)
        transaction = self._bound_transaction()
        if transaction is None:
            return await self._manager.add_all(values)
        transaction.add_all(values)
        await transaction.flush()
        return values

    async def get(
        self,
        identity: object,
        *,
        options: Sequence[Any] = (),
        populate_existing: bool = False,
        with_for_update: bool = False,
    ) -> EntityT | None:
        """Load one entity by primary key."""

        transaction = self._bound_transaction()
        if transaction is None:
            self._reject_one_shot_lock(with_for_update)
            return await self._manager.get(
                self._entity_type,
                identity,
                options=options,
                populate_existing=populate_existing,
            )
        return await transaction.get(
            self._entity_type,
            identity,
            options=options,
            populate_existing=populate_existing,
            with_for_update=with_for_update,
        )

    async def get_one(
        self,
        identity: object,
        *,
        options: Sequence[Any] = (),
        populate_existing: bool = False,
        with_for_update: bool = False,
    ) -> EntityT:
        """Load one entity by primary key or raise SQLAlchemy's no-result error."""

        transaction = self._bound_transaction()
        if transaction is None:
            self._reject_one_shot_lock(with_for_update)
            return await self._manager.get_one(
                self._entity_type,
                identity,
                options=options,
                populate_existing=populate_existing,
            )
        return await transaction.get_one(
            self._entity_type,
            identity,
            options=options,
            populate_existing=populate_existing,
            with_for_update=with_for_update,
        )

    async def merge(
        self,
        entity: EntityT,
        *,
        load: bool = True,
        options: Sequence[Any] = (),
    ) -> EntityT:
        """Merge and flush detached entity state."""

        self._require_entity(entity)
        transaction = self._bound_transaction()
        if transaction is None:
            return await self._manager.merge(entity, load=load, options=options)
        merged = await transaction.merge(entity, load=load, options=options)
        await transaction.flush()
        return merged

    async def delete(self, entity: EntityT) -> None:
        """Delete and flush one entity."""

        self._require_entity(entity)
        transaction = self._bound_transaction()
        if transaction is None:
            await self._manager.delete(entity)
            return
        await transaction.delete(entity)
        await transaction.flush()

    async def find(
        self,
        *criteria: Any,
        options: Sequence[Any] = (),
        order_by: Sequence[Any] = (),
        offset: int | None = None,
        limit: int | None = None,
    ) -> tuple[EntityT, ...]:
        """Find entities using native SQLAlchemy expressions and pagination."""

        _validate_offset_limit(offset=offset, limit=limit)
        statement = select(self._entity_type).where(*criteria).options(*options)
        if order_by:
            statement = statement.order_by(*order_by)
        if offset is not None:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        rows = await self._scalars(statement)
        return tuple(rows.unique())

    async def find_one(
        self,
        *criteria: Any,
        options: Sequence[Any] = (),
        with_for_update: bool = False,
    ) -> EntityT | None:
        """Return exactly one matching entity or None, rejecting duplicates."""

        self._reject_one_shot_lock(with_for_update)
        statement = (
            select(self._entity_type).where(*criteria).options(*options).limit(2)
        )
        if with_for_update:
            statement = statement.with_for_update()
        rows = await self._scalars(statement)
        return rows.unique().one_or_none()

    async def find_one_or_raise(
        self,
        *criteria: Any,
        options: Sequence[Any] = (),
        with_for_update: bool = False,
    ) -> EntityT:
        """Return exactly one matching entity or propagate native result errors."""

        self._reject_one_shot_lock(with_for_update)
        statement = (
            select(self._entity_type).where(*criteria).options(*options).limit(2)
        )
        if with_for_update:
            statement = statement.with_for_update()
        rows = await self._scalars(statement)
        return rows.unique().one()

    async def count(self, *criteria: Any) -> int:
        """Count repository entities matching native SQLAlchemy expressions."""

        statement = select(func.count()).select_from(self._entity_type).where(*criteria)
        return cast(int, await self._scalar(statement))

    async def exists(self, *criteria: Any) -> bool:
        """Return whether any repository entity matches the expressions."""

        candidate = select(1).select_from(self._entity_type).where(*criteria)
        return bool(await self._scalar(select(sql_exists(candidate))))

    async def _execute(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Result[Any]:
        operations = self._active_operations()
        return await operations.execute(statement, params)

    async def _scalar(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> Any:
        operations = self._active_operations()
        return await operations.scalar(statement, params)

    async def _scalars(
        self,
        statement: Executable,
        params: ExecuteParams = None,
    ) -> ScalarResult[Any]:
        operations = self._active_operations()
        return await operations.scalars(statement, params)

    def _active_operations(self) -> EntityManager | EntityTransaction:
        transaction = self._bound_transaction()
        return self._manager if transaction is None else transaction

    def _bound_transaction(self) -> EntityTransaction | None:
        if isinstance(self._operations, EntityTransaction):
            self._operations._require_repository_binding(self._manager)
            return self._operations
        return None

    def _reject_one_shot_lock(self, with_for_update: bool) -> None:
        if with_for_update and self._bound_transaction() is None:
            raise RepositoryBindingError(
                "with_for_update requires a transaction-bound repository"
            )

    def _require_entity(self, entity: object) -> None:
        if not isinstance(entity, self._entity_type):
            raise TypeError(
                f"repository requires {self._entity_type.__qualname__} entities"
            )


def repository[
    EntityT,
    # Python typing cannot link EntityT here while preserving the concrete class.
    RepositoryT: Repository[Any],
](
    entity_type: type[EntityT],
) -> Callable[[type[RepositoryT]], type[RepositoryT]]:
    """Declare one stateless concrete repository for a mapped class."""

    _validate_entity_type(entity_type)
    declaration = _RepositoryMetadata(cast(type[object], entity_type))

    def decorate(
        target: type[RepositoryT],
    ) -> type[RepositoryT]:
        if (
            not isinstance(target, type)
            or target is Repository
            or not issubclass(target, Repository)
            or inspect.isabstract(target)
        ):
            raise SqlAlchemyConfigurationError(
                "repository must be a concrete Repository subclass"
            )
        if target.__init__ is not Repository.__init__:
            raise SqlAlchemyConfigurationError(
                "repository subclasses must inherit the Repository constructor"
            )
        declared_bases = target.__dict__.get("__orig_bases__", ())
        matching_arguments = tuple(
            get_args(base) for base in declared_bases if get_origin(base) is Repository
        )
        if matching_arguments != ((entity_type,),):
            raise SqlAlchemyConfigurationError(
                "repository must directly specialize Repository for its mapped entity"
            )
        if _REFLECTOR.has(_REPOSITORY, target):
            raise SqlAlchemyConfigurationError(
                "repository metadata must be declared directly and only once"
            )
        try:
            return metadata(_REPOSITORY, declaration)(target)
        except BootstrapError as error:
            raise SqlAlchemyConfigurationError(
                "invalid repository declaration"
            ) from error

    return decorate


def _repository_metadata(target: type[Repository[Any]]) -> _RepositoryMetadata:
    declaration = _REFLECTOR.get_own(_REPOSITORY, target)
    if not isinstance(declaration, _RepositoryMetadata):
        if _REFLECTOR.has(_REPOSITORY, target):
            message = "inherited repository metadata is not accepted"
        else:
            message = "custom repository must be directly decorated"
        raise SqlAlchemyConfigurationError(message)
    return declaration


def _validate_offset_limit(*, offset: int | None, limit: int | None) -> None:
    if offset is not None and (
        not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
    ):
        raise ValueError("repository offset must be a non-negative integer or None")
    if limit is not None and (
        not isinstance(limit, int) or isinstance(limit, bool) or limit < 1
    ):
        raise ValueError("repository limit must be a positive integer or None")


__all__ = ["Repository", "repository"]
