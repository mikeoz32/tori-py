"""Table model and SQLAlchemy root module for the Task API."""

from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from tori_py_sqlalchemy import SqlAlchemyModule, SqlAlchemyOptions

from .settings import TaskApiSettings, settings_module


class Base(DeclarativeBase):
    """Metadata root for the application's tables."""


class TaskRow(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))


def create_database_options(settings: TaskApiSettings) -> SqlAlchemyOptions:
    return SqlAlchemyOptions(url=settings.database.url)


database = SqlAlchemyModule.for_root_async(
    imports=[settings_module],
    use_factory=create_database_options,
)
