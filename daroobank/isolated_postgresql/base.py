"""Use normal PostgreSQL behavior with fail-closed synthetic database creation."""
from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLDatabaseWrapper

from .creation import DatabaseCreation


class DatabaseWrapper(PostgreSQLDatabaseWrapper):
    creation_class = DatabaseCreation
