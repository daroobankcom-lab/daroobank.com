# 0234 — the network and TLS plan, and what this application's edge actually emits

Date: 2026-11-27
Status: accepted
Suite: `daroobank/test_network_tls_plan.py` (11 tests, ~0.2 s, no database)

## Context

[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries the network and TLS subject as
an open gate: *"Optional proxy-scheme trust and HSTS settings exist; both are off by default."* and
*"actual network isolation, trusted proxy configuration and header sanitization, approved
hostnames, TLS issuance/renewal, HTTPS/CSRF/cookie checks and HSTS rollback plan; see ADRs
0184–0185."* [DEPLOYMENT.md](../DEPLOYMENT.md) says *"HSTS is off unless
`DAROOBANK_HSTS_SECONDS` is explicitly set to a positive value outside debug."*, that the proxy
flag *"is off by default and ignored in debug"*, and that *"Rate and size limits still have to be
provisioned by the reverse proxy, a CDN or the host before this service faces the public
internet"*; [SECURITY.md](../SECURITY.md) requires *"TLS in transit"*; [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md)
lists *"HSTS off, HTTPS redirection with no trusted proxy header"* among the readiness report's
review conditions; [TESTING_STRATEGY.md](../TESTING_STRATEGY.md) records of the HSTS suite that
*"It does not verify actual TLS, browser caching or recovery"* and of the proxy suite that
*"It does not test or authenticate a real proxy chain"*. [ADR 0184](0184-trusted-proxy-scheme.md) warns *"These checks are not peer
authentication."* and [ADR 0185](0185-opt-in-hsts.md) records that *"Setting the option back to zero
stops new headers but does **not** send `max-age=0` or clear a previously cached HSTS policy."*

What no document contained was a measurement: what a response from this application actually
carries in either configuration, whether any `Access-Control` header or mention exists anywhere,
how the referrer policy splits across the public routes, what the opt-in limiter's refusal looks
like on the wire, and how the public surface compares with the closed header inventory
[ADR 0210](0210-staff-header-inventory.md) pins for staff responses (*"pin the complete header
inventory"* across 1 204 responses).

## Decision

Record [NETWORK_TLS_PLAN.md](../NETWORK_TLS_PLAN.md) as the measurement and the proposal for this
gate, in the form [ADR 0227](0227-read-audit-plan.md), [ADR 0229](0229-attribution-gap-plan.md),
[ADR 0230](0230-mfa-implementation-plan.md), [ADR 0231](0231-secret-rotation-plan.md) and
[ADR 0232](0232-backup-recovery-plan.md) established: an unowned proposal, priced options, numbered
decisions, no implementation. This record changes no behavior. The plan states **Nothing is
implemented.** — no new header, no new middleware, no new environment variable, no new dependency,
no new control and no new command — and this suite holds it to that claim, to its twenty-four
quotes (each must exist both in the plan and in the document it comes from), and to its measured
numbers. The eight decisions — approved hostnames, TLS issuance and renewal, proxy topology and
header sanitization, the HSTS value and its rollback, the real-deployment HTTPS/CSRF/cookie checks,
network isolation, the cross-origin contract for `api/v1`, and the public header inventory — stay
open; answering them is not this record's business.

## Measured behavior

One measurement run, two fresh processes plus the test process, all on this tree:

* **Two header profiles over 55 routes (12 public, 43 staff).** At debug import (13 middleware
  entries) the public HTML class shares six header names, the API and handled-error class eight,
  the staff class ten with 41×302, 1×200 and 1×405 across the 43 routes; in non-debug (14
  middleware entries) `x-frame-options: DENY` appears on every response including the 43 staff 404s
  of the disabled portal gate, and plain HTTP answers 301. Across every probed response in both
  configurations, `strict-transport-security`, every `Access-Control-*` header,
  `cross-origin-resource-policy`, `cross-origin-embedder-policy` and `permissions-policy` never
  appear, and `x-frame-options` never appears in the debug-import profile.
* **HSTS is 0 of 3 features** — seconds 0, includeSubDomains false, preload false — in both
  configurations, so no response carried `Strict-Transport-Security`.
* **The forwarded scheme is stripped by default:** `X-Forwarded-Proto: https` answered 301 without
  the opt-in; with the opt-in and a trusted peer network a trusted peer answered 200 (with
  `max-age=60` under a 60-second test value), an untrusted peer 301, and a direct HTTPS request
  200; the flag without `DAROOBANK_TRUSTED_PROXY_CIDRS` fails startup naming that variable; in
  debug the settings dump reads `[true, null, 13]`.
* **CORS does not exist in the tree:** 0 occurrences of `Access-Control` in non-test `.py` files,
  no CORS middleware, and 0 `Access-Control-*` headers on any response (before this record was
  written the temporary probe, since deleted, also counted 0 occurrences in every document).
  `Cross-Origin-Opener-Policy: same-origin` comes from Django's default, which `settings.py` never
  sets; the other three policy headers are never sent.
* **Referrer-Policy splits 7 of 12:** `no-referrer` on the five read paths and both health probes,
  `same-origin` on home, about, prices, robots and sitemap, in both configurations; staff is always
  `same-origin`.
* **The limiter's refusal, with the flag forced on and the limit patched to 3:** 200, 200, 200,
  then 429 with `Retry-After: 60` and an empty body carrying the public privacy headers; one row
  per `REMOTE_ADDR` even when `X-Forwarded-For` changes, the stored key is not the address, and
  `HTTP_X_FORWARDED_FOR` is read by 0 non-test modules. The flag defaults to off with no DEBUG
  term; the constants are 120 reads and a 60-second window under `staff_security.public_read.v1`.
* **Static counts:** 63 templates (9 root, 53 staff, 1 partial); `site.css` 25,166 bytes and
  `staff.css` 8,245 bytes, both named in DESIGN_SYSTEM.md; `.github/workflows/checks.yml` is 217
  lines with 0 mentions of `tls`, `hsts`, `proxy`, `https` or `header`.
* **Cookie flags are settings-level facts in these sweeps:** `SESSION_COOKIE_SECURE` and
  `CSRF_COOKIE_SECURE` are true only in non-debug, `SESSION_COOKIE_HTTPONLY` and
  `SESSION_COOKIE_SAMESITE='Lax'` hold in both, and no probed GET set any `Set-Cookie`.

## Red checks

After the plan, the suite and the neighbour patches existed, twenty-two mutations were applied one
at a time to a byte-identical backup of the tree (`sha256sum` recorded before, re-verified after
every restore, final check rc=0), each followed by a run of
`daroobank/test_network_tls_plan.py`, each run required to fail. Every mutation went red and the
suite ended green:

1. Plan: `## What is true today, measured` renamed — `test_the_plan_states_its_own_shape`.
2. Plan: `### The two header profiles` renamed — `test_the_plan_states_its_own_shape`.
3. Plan: decision 8 unnumbered — `test_the_plan_states_its_own_shape`.
4. Plan: "The selected approach is to enable HSTS immediately." inserted —
   `test_the_plan_is_an_unowned_proposal_that_implements_nothing` (forbidden-selection list).
5. Plan: both instances of the ADR 0185 rollback quote deleted —
   `test_the_plan_quotes_the_requirements_it_is_priced_against`.
6. ADR 0185: the quoted rollback sentence reworded in its source —
   `test_the_plan_quotes_the_requirements_it_is_priced_against`.
7. Plan: `then 429 with \`Retry-After: 60\`` became `then 503` —
   `test_the_plan_states_the_measured_numbers`.
8. Plan: `41 answers are 302` became `42 answers` — `test_the_plan_states_the_measured_numbers`.
9. Plan: `55 routes: 12 public and 43 staff` became 54/12/42 —
   `test_the_plan_states_the_measured_numbers`.
10. settings.py: the pinned HSTS comment reworded —
    `test_the_plan_quotes_the_requirements_it_is_priced_against`.
11. settings.py: `SECURE_HSTS_SECONDS` default `0` became `60` —
    `test_the_settings_shape_is_the_measured_one`.
12. settings.py: `TRUSTED_PROXY_SCHEME_NETWORKS = ()` and `SECURE_PROXY_SSL_HEADER = None`
    turned on — `test_the_settings_shape_is_the_measured_one`.
13. settings.py: a new `os.environ.get("DAROOBANK_CORS_ORIGINS")` read appended —
    `test_no_new_header_middleware_environment_or_dependency_exists`.
14. middleware.py: `class CorsMiddleware` added — `test_the_settings_shape_is_the_measured_one`
    (the AST class scan).
15. middleware.py: the pinned `TrustedProxySchemeMiddleware` docstring sentence reworded —
    `test_the_plan_quotes_the_requirements_it_is_priced_against`.
16. middleware.py: a `Permissions-Policy` string added —
    `test_no_new_header_middleware_environment_or_dependency_exists`.
17. DEPLOYMENT.md: the plan link removed —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
18. CHANGELOG.md: the `## 2026-11-27 — ` heading date changed —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
19. Evidence row: the measured gate sentence removed —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
20. Evidence row: the open gate sentence truncated —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
21. ADR index: the 0234 bullet deleted —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
22. A temporary `daroobank/test_zz_probe_headers.py` recreated —
    `test_no_new_header_middleware_environment_or_dependency_exists`.

Two mutations initially slipped — a selection phrase the forbidden list did not yet carry and a
class the AST scan did not yet walk — which is why both checks exist in the suite in their present
form; each was re-run red after the suite grew the assertion.

## Consequences

* The gate row in [PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) now carries the
  measurements in its evidence cell while both of its quoted gate sentences stay verbatim in
  place, because other suites pin them; the open half points at the plan's eight decisions and
  states that answering them remains unassigned work.
* [DEPLOYMENT.md](../DEPLOYMENT.md), [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md),
  [SECURITY.md](../SECURITY.md), [TESTING_STRATEGY.md](../TESTING_STRATEGY.md) and
  [DESIGN_SYSTEM.md](../DESIGN_SYSTEM.md) each gained a sentence that names what was measured and
  links the plan and this record; [CHANGELOG.md](../CHANGELOG.md) carries the entry.
* The public surface now has a measured inventory and a suite that re-measures the database-free
  part of it on every run, which is the public counterpart of the staff inventory ADR 0210
  established — documentation of what exists, not a policy for what should.
* Two global pins move with this record and must be recounted from the tree rather than from this
  text: the test-module count in `daroobank/test_mfa_implementation_plan.py` and
  `daroobank/test_secret_rotation_plan.py`, and the document, record, link, anchor and `Suite:`
  line counts in `daroobank/test_document_links.py`.
* Nothing here configures TLS, a proxy, a header, an environment variable or a dependency. Any of
  those remains a change for whoever answers the decisions, with its price already counted in the
  plan's option table.

## Limitations

- **The profiles are synthetic and local.** Fresh processes with synthetic secrets and hosts, the
  Django test client, a throwaway database and no browser, no proxy and no certificate: they
  measure what this code emits, not what a deployment serves. Neither a real TLS handshake, a
  cached HSTS policy, an actual intermediary chain nor a CDN's own headers was exercised, which is
  the same limit [ADR 0184](0184-trusted-proxy-scheme.md) and [ADR 0185](0185-opt-in-hsts.md)
  record for their own suites.
- **The in-process profile is the import-time configuration.** Django forces `settings.DEBUG` false
  inside a test run, so the debug profile is named for the configuration that built the stack when
  `DAROOBANK_DEBUG=1` was read; the non-debug numbers come from separate processes started with
  `DAROOBANK_DEBUG=0`.
- **Health readiness inside a test transaction is a harness artifact.** `database_ready` refuses an
  atomic block, so `health_ready` answers 503 in a `TestCase` and 200 outside one; the plan records
  the outside measurement and says why the inside one differs.
- **No option was evaluated for correctness or lawfulness.** Whether HSTS should be enabled, which
  origins may consume `api/v1`, which headers the edge should emit and who may approve any of it
  are questions for named owners; the seven options are priced inventories, not recommendations,
  and the eight decisions stay open.
- **The suite pins documents, counts and the database-free response shape.** It cannot tell whether
  the decisions will be answered, whether a certificate or proxy will behave as these sweeps
  suggest, or whether the plan is the right plan; forcing the questions and the counts is all it
  does.
