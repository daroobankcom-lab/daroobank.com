"""Read-only, selected PostgreSQL session and table-privilege observations."""
from django.db import connection


def inspect_access(table_names):
    """Return aggregate clues in one statement, not an access audit or certification."""
    with connection.cursor() as cursor:
        cursor.execute('''
            WITH names AS (
                SELECT DISTINCT name FROM pg_catalog.unnest(%s::text[]) AS item(name)
            ), resolved AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', name)) AS oid FROM names
            ), relations AS (
                SELECT DISTINCT c.oid, c.relkind, c.relrowsecurity, c.relforcerowsecurity
                FROM resolved r JOIN pg_catalog.pg_class c ON c.oid = r.oid
            ), tables AS (
                SELECT oid, relrowsecurity, relforcerowsecurity FROM relations WHERE relkind IN ('r', 'p')
            ), active_role AS (
                SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls
                FROM pg_catalog.pg_roles WHERE rolname = current_user
            ), transport AS (
                SELECT CASE WHEN pg_catalog.inet_client_addr() IS NULL THEN 'unix_socket'
                            WHEN ssl.ssl IS TRUE THEN 'tls'
                            WHEN ssl.ssl IS FALSE THEN 'tcp_without_tls'
                            ELSE 'unknown' END AS kind
                FROM (SELECT 1) AS one
                LEFT JOIN pg_catalog.pg_stat_ssl ssl ON ssl.pid = pg_catalog.pg_backend_pid()
            )
            SELECT
                (SELECT count(*) FROM names),
                (SELECT count(*) FROM resolved WHERE oid IS NULL),
                (SELECT count(*) FROM relations WHERE relkind NOT IN ('r', 'p')),
                (SELECT count(*) FROM tables),
                current_user <> session_user,
                active_role.rolsuper, active_role.rolcreatedb, active_role.rolcreaterole,
                active_role.rolreplication, active_role.rolbypassrls,
                pg_catalog.has_database_privilege(current_user, pg_catalog.current_database(), 'CREATE'),
                (SELECT pg_catalog.has_schema_privilege(current_user, oid, 'CREATE')
                 FROM pg_catalog.pg_namespace WHERE nspname = 'public'),
                (SELECT kind FROM transport),
                pg_catalog.current_setting('transaction_read_only') = 'on',
                (SELECT count(*) FROM tables WHERE pg_catalog.has_table_privilege(current_user, oid, 'SELECT')),
                (SELECT count(*) FROM tables WHERE pg_catalog.has_table_privilege(current_user, oid, 'INSERT')),
                (SELECT count(*) FROM tables WHERE pg_catalog.has_table_privilege(current_user, oid, 'UPDATE')),
                (SELECT count(*) FROM tables WHERE pg_catalog.has_table_privilege(current_user, oid, 'DELETE')),
                (SELECT count(*) FROM tables WHERE pg_catalog.has_table_privilege(current_user, oid, 'TRUNCATE')),
                (SELECT count(*) FROM tables WHERE relrowsecurity),
                (SELECT count(*) FROM tables WHERE relforcerowsecurity)
            FROM active_role
        ''', [list(table_names)])
        row = cursor.fetchone()
    keys = ('expected_relations', 'unresolved_relations', 'non_table_relations', 'selected_tables', 'role_switched',
            'role_superuser', 'role_create_database', 'role_create_roles', 'role_replication', 'role_bypass_rls',
            'database_create_privilege', 'public_schema_create_privilege', 'connection_transport', 'transaction_read_only',
            'tables_select', 'tables_insert', 'tables_update', 'tables_delete', 'tables_truncate',
            'tables_rls_enabled', 'tables_rls_forced')
    return dict(zip(keys, row, strict=True))
