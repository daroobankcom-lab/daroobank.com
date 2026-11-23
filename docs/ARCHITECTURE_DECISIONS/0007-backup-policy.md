# ADR 0007: development database backups

Status: superseded by PostgreSQL-only operations; the former development backup utility has been removed. See [ADR 0009](0009-postgresql-only.md).

Use PostgreSQL-native `pg_dump` and `pg_restore` against an isolated, newly created database as described in the [development guide](../DEVELOPMENT_GUIDE.md#postgresql-backup-and-isolated-restore). Dumps contain all database contents, including password hashes and sessions; they are not automatically encrypted, stored off-host or retained. Archive listing is not a restore test. Never restore into a live or valuable database, and protect both dumps and credentials. A production backup system requires separate encryption, access control, retention, monitoring, off-host copies, recovery objectives and regular verified recovery drills. No production backup or recovery service is implemented by this ADR.
