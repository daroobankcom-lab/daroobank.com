# ADR 0101: PostgreSQL trigger session clues

Status: development-only implementation, 24 November 2026; extends [ADR 0070](0070-postgresql-catalog-clues.md).

## Decision

Extend the existing one-statement catalog inspection with two fixed aggregate fields. `trigger_session_mismatches` counts triggers on resolved managed tables whose enabled mode does not fire in the inspecting session: replica-only (`R`) in `origin` or `local`, and origin-only (`O`) in `replica`. Disabled (`D`) triggers remain in the existing `disabled_triggers` count, while always-enabled (`A`) triggers are not a mode mismatch. `session_replication_role_replica` is 1 if the inspecting connection is in `replica` mode and 0 otherwise. Either new nonzero count produces `attention`; no trigger names, functions, records or role values are emitted.

Replica-only triggers may be intentional in a replication topology, so a mismatch is a clue requiring investigation, not proof of a defect. The `replica` warning applies even when no selected triggers are found because this mode can suppress ordinary PostgreSQL foreign-key triggers. This observes one connection at one statement; other sessions, later settings, other schemas and unselected tables are not assessed. It cannot detect missing triggers, prove trigger definitions or functions safe, or certify foreign-key data, replication topology, permissions, integrity or production readiness. Do not change replication-role settings or repair objects on a real system based on this tool alone.

## Evidence

Synthetic PostgreSQL tests show a replica-only `BEFORE INSERT` trigger does not fire in origin mode, verify always and disabled mode counts, and confirm command failure without names for a trigger on a managed table. With a privileged disposable test role, a separate transaction demonstrates that replica mode allows an otherwise rejected foreign-key violation; the report flags the session and its origin-only internal triggers, and `local` follows origin trigger behavior. Another superuser-only transaction switches a synthetic table's internal foreign-key triggers to replica-only, demonstrates an origin-mode violation, and confirms the mismatch. Switching them to always-enabled prevents a later violation but does not validate the row previously inserted. Tests skip when their required disposable role privileges are absent. All mutations are rolled back. One-statement/read-only and clean-schema tests remain in place. These tests do not establish behavior across all PostgreSQL versions, replication arrangements or concurrent sessions.
