"""Fail if the ORM models and the Alembic migrations drift apart."""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.db import get_engine
from app.models import Base

MIGRATION_ONLY_INDEXES = {"ix_contacts_search_trgm", "ix_messages_text_trgm"}


def _include(obj, name, type_, reflected, compare_to):
    return not (type_ == "index" and name in MIGRATION_ONLY_INDEXES)


def test_models_match_migrations():
    with get_engine().connect() as conn:
        ctx = MigrationContext.configure(conn, opts={"include_object": _include})
        diff = [
            d
            for d in compare_metadata(ctx, Base.metadata)
            if d[0] != "remove_table" or d[1].name != "alembic_version"
        ]
    assert diff == []
