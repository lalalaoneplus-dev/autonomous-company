from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def configure_database(url: str | None = None) -> Engine:
    global engine, SessionLocal
    database_url = url or settings.database_url
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)
    if database_url.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine


def get_engine() -> Engine:
    return engine or configure_database()


def get_db() -> Generator[Session, None, None]:
    if SessionLocal is None:
        configure_database()
    assert SessionLocal is not None
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_schema() -> None:
    from .models import Base

    Base.metadata.create_all(get_engine())
