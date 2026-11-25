# ADR 0102: synthetic backup argument guards

Status: development-only guide, 24 November 2026; extends [ADR 0091](0091-synthetic-backup-guide-fail-stop.md).

## Decision

The executable synthetic backup example now rejects non-absolute archive paths before any client command, supplies an option terminator before archive operands, and limits the source database variable to 1–63 ASCII letters, digits or underscores. The block sets `LC_ALL=C` within its subshell for predictable shell ranges. This deliberately rejects some valid PostgreSQL database names and libpq connection strings; use an explicitly verified synthetic database with a simple name for this example. A libpq connection string supplied as a database name can contain connection options, so merely quoting it does not make it an ordinary database name.

This is fail-stop argument validation, not proof of an isolated server, safe directory, server identity, correct DNS, credentials, permissions, safe inherited libpq environment or source data. Absolute paths can contain symlinks or refer to untrusted locations. Noclobber and restrictive umask remain subject to shell/filesystem semantics, failed archives can remain, and this is neither a production backup procedure nor a substitute for encryption and recovery policy. Verify all targets and use synthetic data only.

## Evidence

Offline shell tests execute the exact documented block with stubbed commands and verify early rejection of relative/option-like paths, connection strings, disallowed characters and overlong names; a 63-character simple name and an archive path containing spaces are accepted. Stubbed restore calls require the option terminator. Existing failure-at-each-step, collision, missing setting and file-mode tests remain. A one-off PostgreSQL 16.2 synthetic-cluster run checked a pre-existing target was not restored into, and then restored successfully into a freshly created target using an absolute archive path containing spaces. This is a limited sample, not a guarantee for all shells, clients, filesystems or environments.
