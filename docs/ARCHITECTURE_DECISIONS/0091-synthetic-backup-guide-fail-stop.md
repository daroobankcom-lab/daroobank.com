# ADR 0091: fail-stop synthetic backup example

Status: development-only documentation and tests, 24 November 2026; extends [ADR 0007](0007-backup-policy.md).

## Context and decision

The previous manual backup example listed shell commands independently. In a normal shell without exit-on-error, a failed `createdb` could be followed by a restore into an already existing target; failures of earlier stages could similarly be ignored. The example now runs as one subshell with required-variable checks, shell noclobber, restrictive umask, noninteractive PostgreSQL tools and an `&&` chain: restore is reached only after a new target is successfully created and all earlier stages succeed. It is explicitly for a disposable synthetic cluster, not production data.

This is not a fully safe backup tool: users can run lines separately, choose the wrong server, use an untrusted directory or race with other actors. Noclobber depends on shell/filesystem semantics. A failed dump may leave an incomplete file; a failed restore may leave a newly created database. Independently verify identities before cleanup. The commands do not provide encryption, authenticated archives, atomic publication, retention, automation or production authorization.

## Evidence

Offline tests execute the actual documented shell block against fake binaries, check success order, every stage failure, existing archive preservation and missing required variables. A separate one-off test on an isolated synthetic PostgreSQL 16 cluster showed that a pre-existing empty target remains empty when creation fails and that a newly created target can be restored and checked; both test targets were removed only after their creation was confirmed. These checks cover selected failure sequences, not every shell, filesystem, crash, concurrency or operational scenario.
