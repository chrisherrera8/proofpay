from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def make_engine(database_url: str, schema: str) -> Engine:
    url = make_url(database_url)
    if url.drivername in ("postgresql", "postgres"):
        url = url.set(drivername="postgresql+psycopg")
    engine = create_engine(url, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, _record):
        # Quote the identifier; the schema name comes from our own env, not users.
        with dbapi_conn.cursor() as cur:
            cur.execute(f'SET search_path TO "{schema}"')
        dbapi_conn.commit()

    return engine


_settings = get_settings()
engine = make_engine(_settings.database_url, _settings.db_schema)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
