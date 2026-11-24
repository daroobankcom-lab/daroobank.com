"""Create a fresh synthetic test database without dropping an existing one."""
import re

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError
from django.db.backends.postgresql.creation import DatabaseCreation as PostgreSQLDatabaseCreation

TEST_NAME = re.compile(r'test_daroobank_(?:synthetic|restore|browser)_[0-9a-f]{32}\Z')


class DatabaseCreation(PostgreSQLDatabaseCreation):
    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        # Unlike Django's default --noinput behavior, never drop or reuse an
        # existing database after a name collision. CREATE itself is atomic.
        if keepdb:
            raise ImproperlyConfigured('Isolated tests cannot reuse a database.')
        name = self._get_test_db_name()
        if not isinstance(name, str) or not TEST_NAME.fullmatch(name):
            raise ImproperlyConfigured('Invalid isolated synthetic test database name.')
        parameters = {'dbname': self.connection.ops.quote_name(name), 'suffix': self.sql_table_creation_suffix()}
        with self._nodb_cursor() as cursor:
            try:
                self._execute_create_test_db(cursor, parameters, keepdb=False)
            except DatabaseError as exc:
                cause = exc.__cause__
                if (getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None)) == '42P04':
                    raise ImproperlyConfigured('Isolated test database already exists; it was not reused or dropped.') from exc
                raise
        return name

    def _clone_test_db(self, suffix, verbosity, keepdb=False):
        # The isolated runner rejects parallel tests; don't expose Django's
        # destructive clone-on-collision fallback through a direct call either.
        raise ImproperlyConfigured('Isolated tests cannot clone a database.')
