# 0228 — an opt-in limit on public reads that records nothing about what was read

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_public_read_limit.py` (11 tests, ~1.2 s)

## Context

[ADR 0223](0223-no-abuse-protection.md) measured that nothing in this application limits a public
request: 48 sequential anonymous reads of six routes all answered 200, no module sent
`Retry-After`, the only limiter was the debug-only staff login window of
[ADR 0181](0181-development-staff-login-throttle.md), and [DEPLOYMENT.md](../DEPLOYMENT.md)
assigned rate limiting to the edge. [SECURITY.md](../SECURITY.md) lists rate limits among the
controls this product is supposed to have, and the Phase 1 evidence still carries abuse protection
as open. The measurement was honest, but it left an operator with nothing to turn on: a
development preview that is reachable from the public internet — which is what the staff portal is
in debug mode — has no in-application floor at all, and "provision it at the edge" is a
requirement nobody has arranged.

Two constraints decided the shape before any code was written. The first is
[ADR 0221](0221-no-read-audit.md) and [ADR 0227](0227-read-audit-plan.md): nothing here records
that a read happened, and implementing a read audit is a decision this project has deliberately
not made. A limiter that stored what was read, by whom, or when, would be an access log wearing a
rate limit's clothes. The second is ADR 0223's own finding that the login limiter fails **closed**
— an unavailable counter answers 503 — which is right for authentication and wrong for a public
page, because refusing every read when a counter table is unreachable turns one database problem
into an outage.

## Decision

Add a second limiter, opt-in and off by default in every environment, that counts public reads and
refuses the ones over the limit while storing nothing but the count:

* `staff_security/read_limit.py` holds the window: `READ_LIMIT` 120, `WINDOW` 60 seconds, one
  atomic block per read that sets `lock_timeout` 1 s and `statement_timeout` 2 s, upserts the
  counter with `INSERT … ON CONFLICT (client_key) DO UPDATE … RETURNING started_at, reads,
  clock_timestamp()`, rolls the window over when it is older than the window, caps the stored
  count at `READ_LIMIT + 1`, and returns `(outcome, retry_after)` where the outcome is `allowed`,
  `limited` or `unavailable`.
* `daroobank/middleware.py` gains `PublicReadLimitMiddleware`, one entry directly above
  `SessionMiddleware`, so a refused read creates no session row. It counts only `GET`, never a
  staff path and never a health probe, and answers an over-limit read with **429**, an empty body,
  a `Retry-After` delay and the public privacy headers — which it sets itself, because a refusal is
  produced before URL resolution and so never reaches the middleware that would set them.
* `staff_security/models.py` gains `PublicReadWindow` with exactly three columns and
  `default_permissions = ()`, plus migration `staff_security/0002_publicreadwindow.py`.
* `DAROOBANK_PUBLIC_READ_LIMIT` / `PUBLIC_READ_LIMIT_ENABLED` turn it on. Unlike the login
  throttle, the setting has no debug term: the point is a floor in a non-debug deployment, and a
  control that cannot be enabled where it is needed is not a control.
* An unavailable limiter **fails open**: an unkeyable address, a non-PostgreSQL backend, an open
  transaction, a backwards clock or a `DatabaseError` all return `unavailable`, and the middleware
  serves the read. This is the deliberate opposite of the login limiter.
* The client key is `salted_hmac('staff_security.public_read.v1', normalized REMOTE_ADDR)`. No raw
  address is stored, and because the login window's scope is `staff_security.login.client.v1`, one
  address has two different keys and the two tables cannot be joined.

Then pin it, run the whole suite against it, and move every pin the change broke rather than
deleting one.

## Measured behavior

| Measurement | Result |
|---|---|
| Opt-in state | `PUBLIC_READ_LIMIT_ENABLED` is `False` in the synthetic environment and is computed as `DAROOBANK_PUBLIC_READ_LIMIT == '1'` with no debug term; `STAFF_LOGIN_THROTTLE_ENABLED` stays `False` too, so both limiters are off wherever the suite runs |
| The window | `READ_LIMIT` is 120, `WINDOW` is `timedelta(seconds=60)`, `SCOPE` is `staff_security.public_read.v1`, and the counter is written inside one atomic block under a 1 s lock timeout and a 2 s statement timeout |
| What the table holds | exactly `client_key` (primary key, `max_length=64`, not editable), `started_at` (indexed) and `reads`; no path, route, query, user agent, account or per-read timestamp, and no permissions |
| Client identity | the key is 64 hexadecimal characters, is not the address, and `::ffff:203.0.113.7` keys to the same client as `203.0.113.7`; the login key for the same address is a different digest |
| Unkeyable clients | `None`, `''`, `'not-an-address'`, `'fe80::1%eth0'`, `'203.0.113.7 extra'` and a 46-character string all key to `None`, are served, and write no row |
| Both limiters off, the default | 48 reads — six public routes eight times each — all answer 200, none carries `Retry-After`, `X-RateLimit-*`, `X-Rate-Limit-*` or `RateLimit-*`, and no row appears in any of the 24 project tables |
| Limiter on, under the limit | five reads by one client answer 200 and leave exactly one row with `reads = 5`; a second address leaves a second row; `StaffLoginWindow` and `django_session` stay empty |
| Limiter on, over the limit | with `READ_LIMIT` patched to 3, three reads answer 200 and the fourth answers **429** with `content == b''`, `Retry-After` between 1 and 60, `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex, follow` and the content-security policy, and creates no session row |
| What the refusal stored | nothing about the request: no marker from the query string, the user agent, the path or the address appears anywhere in the table after the refusal |
| Window rollover | with `started_at` set 61 seconds in the past, the next read opens a new window and is served; with it set an hour in the **future**, the counter is neither reset nor used to refuse — a backwards clock yields `unavailable` and the read is served |
| Excluded requests | `/staff/`, `/staff/products/`, `/health` and `/health/ready` are never counted and write no row even with `READ_LIMIT` at 1, and neither `POST` nor `HEAD` is counted |
| Failure | a `DatabaseError` inside the atomic block returns `('unavailable', 0)`, and the middleware with `consume_read` patched to that answer serves **200** — the opposite of the login limiter's 503 |

## What the change cost

The whole suite ran against a copy of the tree holding this change, at seed 474401: **1658 tests
in 622.8 s, 20 failures**. Nineteen were pins this change moved; the twentieth was pre-existing —
the decision index listed 0227 above 0226 — and was fixed on its own in `f2168cc`.

| Suite | Pins that moved |
|---|---|
| `test_no_read_audit` (ADR 0221) | the middleware stack 12 → 13 entries, project middleware 7 → 8, project models 23 → 24, and the table inventory 32 → 33 with `staff_security_publicreadwindow` added |
| `test_no_abuse_protection` (ADR 0223) | `429` in one non-test module → two, `Retry-After` in none → one, the limiter-class scan now names `PublicReadLimitMiddleware`, and "no middleware limits requests" became "the only limiting middleware is the opt-in read limiter" |
| `test_migration_reversibility` (ADR 0216) | `staff_security` 1 → 2 migrations and 16 → 17 in total, applied 31 → 32, a fresh database 32 → 33 tables / 276 → 279 columns / 108 → 111 indexes / 136 → 138 constraints with foreign keys unchanged at 50, and 16 → 17 tables left after `migrate catalog zero` |
| `test_populated_rollback_drill` (ADR 0225) | the fixture now fills 24 project tables — the read window gets one row, because a table an operator must back up or roll back has to be in the drill — applied 31 → 32, applied after `catalog zero` 20 → 21 with 17 tables left, a blocked rollback 30 → 31 applied and 31 → 32 tables, and the forward migrate 31 → 32 |
| `test_actor_attribution_inventory` (ADR 0220) | 23 → 24 project models, and one more unattributed model with the reason written down |
| `test_environment_documentation` (ADR 0222) | fifteen → sixteen variables read, all of them in `daroobank/settings.py` |
| `test_deployment_readiness` (ADR 0217) | a freshly created database reports 31 → 32 unapplied migrations |
| `test_no_django_admin` (ADR 0218) | the table inventory 32 → 33 |
| `test_read_audit_plan` (ADR 0227) | the middleware tuple 12 → 13 and the project model count 23 → 24 |

With the pins moved, the nine affected suites ran 72 tests green at seed 474601 and the two schema
suites ran 14 green at seed 474604.

## Red checks

Eight code regressions, each applied alone to one file and reverted afterwards:

| Regression | Result |
|---|---|
| `PUBLIC_READ_LIMIT_ENABLED = True` in `settings.py` | 5 failures across three suites: both public-read sweeps, the two-limiter pin, the limiter-shape pin and the middleware-stack pin |
| `client_key` returns the raw normalized address | 4 failures: the scope pin, the single-row count, the second client's row and the refusal |
| `path = models.CharField(max_length=200, null=True)` added to `PublicReadWindow` | 1 failure — the model holds no request detail — and 3 errors, `column staff_security_publicreadwindow.path does not exist` |
| `response['Retry-After'] = …` deleted from the refusal | 1 error, `KeyError: 'retry-after'` |
| The middleware counts `POST` as well as `GET` | 1 failure: a non-GET request is not counted |
| `except DatabaseError` returns `('limited', 60)` instead of `('unavailable', 0)` | 1 failure: an unkeyable or failing client is served rather than refused |
| The middleware moved below `SessionMiddleware` | 3 failures: the limiter-shape pin and both middleware pins |
| The health-probe exclusion deleted | 6 failures in the exclusion test's subtests |

Four documentation regressions were checked the same way. Deleting the variable's line from
`.env.example` fails the template-drift check. Replacing both mentions of it in
[DEPLOYMENT.md](../DEPLOYMENT.md) fails the production-audience check, while *renaming* them fails
only the reverse-direction check that no document names a variable the code does not read — a
renamed variable still contains the original name, so a presence assertion cannot see it, which is
why the guide is pinned in both directions. Deleting this record's entry from the decision index
fails three checks at once: the index order, the index completeness and the link count.

Each patch was asserted to apply before the run, and each revert was compared byte for byte with
`filecmp` against a copy taken beforehand, so a red check that silently did not apply cannot pass.

## Consequences

* An operator now has something to turn on, and [DEPLOYMENT.md](../DEPLOYMENT.md) says what it is
  and is not: the sentence "the application has no rate limit" became "no rate limit that is on by
  default", the configuration table gained a row, and the edge provision is still required — the
  opt-in limiter is named as defense in depth, not as that provision.
* [SECURITY.md](../SECURITY.md) and [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) each gained an
  "Opt-in public read limit" section, and `.env.example` gained the sixteenth variable. The
  development guide records the maintenance the limiter creates.
* The schema is now 33 tables, 279 columns, 111 indexes, 138 constraints, 50 foreign keys and 32
  applied migrations from 17 project migrations; every pin that counted them moved, and the
  rollback drill now fills, destroys and fails to restore the read window along with the rest.
* ADR 0221's property survives in the form that matters: no read is **recorded**. The counter holds
  a keyed digest, a window start and a number. With the limiter on, a read does write to the
  database — an increment, not a record — and ADR 0221's two sweeps run with it off, which is the
  default and what every environment sets.
* ADR 0223's suite now pins two opt-in limiters and one limiting middleware instead of none, and
  its record carries a pointer here. The login 429 still sends no `Retry-After`.

## Limitations

* Not load-tested. Nothing here measures throughput, latency, connection use or behavior under
  real concurrency; 120 reads per minute is a round number far above any human reading pattern,
  not a measured one.
* One row per distinct client key, kept forever. `consume_read` reuses a row and rolls its window
  over, so the table grows with the number of distinct addresses ever seen and nothing prunes it:
  `cleanup_staff_login_windows` handles only the login table, and ADR 0219's inventory pins the
  twelve commands that exist. Whoever enables this limiter owns that maintenance.
* Keyed by `REMOTE_ADDR` as the server sees it. Behind a proxy that does not set it per client,
  every reader shares one key and one window; behind one that forwards `X-Forwarded-For` into it
  without the trusted-proxy review ADR 0184 requires, a client chooses its own key.
* Failing open means the limit is not a guarantee: while the counter is unreachable, public reads
  are unlimited. That is the chosen trade, and it is the opposite of the login limiter's.
* The refusal is an empty 429. A non-browser client gets a status and a delay and no reason, and a
  browser gets a blank page; no public error page explains it, because an explanation would be a
  place to put text nobody has reviewed.
* The threshold is never exercised end to end: the refusal, rollover and exclusion tests patch
  `READ_LIMIT` down to 3, 1 or 0 rather than making 120 requests, so 120 is pinned as a constant
  in code and the refusal path is pinned at a smaller number.
* One key can cover many people. IPv6 privacy extensions, carrier NAT, a shared office egress or a
  crawler-friendly household all mean a reader who did nothing can be refused.
* The model is named `PublicReadWindow` and the module `read_limit`. ADR 0221's scan for
  access-record names looks for `access`, `audit`, `event`, `log`, `track` and `visit`, and "read"
  is not among them, so the pin passes on the name; what makes this a counter rather than a record
  is the three columns, which the suite pins separately.
