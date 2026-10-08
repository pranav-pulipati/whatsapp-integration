from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.config import get_settings
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Indexes managed only in migrations (expression/opclass indexes the ORM can't express).
MIGRATION_ONLY_INDEXES = {"ix_contacts_search_trgm", "ix_messages_text_trgm"}


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ANN001
    return not (type_ == "index" and name in MIGRATION_ONLY_INDEXES)


def _url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
