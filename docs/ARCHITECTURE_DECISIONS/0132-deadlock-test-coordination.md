# ADR 0132: coordinate the synthetic identity deadlock probe at the lock holder

Status: development test reliability change, 24 November 2026; no application write behavior changed.

A full synthetic suite run on `8398edd`, seed `8924301`, failed the identity deadlock probe: the service reported `55P03` (lock timeout) where the test required `40P01` (deadlock). Another full suite on the same snapshot with seed `8924302` passed while both ran on the same host. The failure does not establish a production defect; its exact scheduling cause was not determined.

The selected test still requires a real PostgreSQL `40P01` to be translated by the service and still checks no new review remains. The manual lock-holding worker now observes its own backend in `pg_blocking_pids(service_pid)` and immediately requests the reverse lock, avoiding the extra main-thread handoff after wait observation. Both connections have longer bounded lock/statement timeouts and the coordination itself has bounded cancellation/waits. No permission to change the server's `deadlock_timeout` is required.

Deadlock victim selection, host scheduling, timeout settings, crashes and all other interleavings remain outside this selected test. It can still fail when the service is not chosen as victim or the host is overloaded; do not silently accept a timeout as a deadlock. Test reruns and shuffled seeds provide only sample evidence, not proof of determinism or production concurrency safety.
