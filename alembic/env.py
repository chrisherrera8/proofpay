from alembic import context
from sqlalchemy import text

import app.models  # noqa: F401  (registers tables on Base.metadata)
from app.config import get_settings
from app.db import Base, make_engine

config = context.config
target_metadata = Base.metadata
settings = get_settings()


def run_migrations_online() -> None:
    engine = make_engine(settings.database_url, settings.db_schema)
    with engine.connect() as connection:
        # The engine's search_path is DB_SCHEMA, so tables and alembic_version land there.
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.db_schema}"'))
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
