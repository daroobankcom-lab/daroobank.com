# The network and TLS plan, and what this application's edge actually emits

`docs/PHASE1_RELEASE_EVIDENCE.md` carries the whole subject as an open gate: *"Optional proxy-scheme
trust and HSTS settings exist; both are off by default."*, and *"actual network isolation, trusted
proxy configuration and header sanitization, approved hostnames, TLS issuance/renewal,
HTTPS/CSRF/cookie checks and HSTS rollback plan; see ADRs 0184–0185."*
`docs/DEPLOYMENT.md` says *"HSTS is off unless `DAROOBANK_HSTS_SECONDS` is explicitly set to a
positive value outside debug."*, that *"The application does not enable subdomain inclusion or
preload; an upstream proxy may independently set HSTS."*, that for the proxy flag *"The flag is off
by default and ignored in debug."*, that a trusted-peer list is *"**not** a firewall or proof that
the peer is an authorized proxy: the proxy must overwrite incoming forwarding headers, preserve the
approved Host, and the app must be network-restricted"*, that *"Rate and size limits still have to
be provisioned by the reverse proxy, a CDN or the host before this service faces the public
internet"*, and that database links should use *"`verify-full` for any connection that leaves the
host, so the server certificate is checked and the link is encrypted in transit"*.
`docs/SECURITY.md` requires *"TLS in transit; encryption at rest where appropriate with isolated
managed keys and rotation; least-privilege DB/worker credentials."*
`daroobank/settings.py` keeps *"HSTS is off until an operator explicitly selects a reviewed TLS
policy."* and describes proxy trust as *"Disabled by default and in debug; forwarding is only
meaningful when direct"* over *"peer networks and an independently secured proxy are explicitly
configured."*
`daroobank/middleware.py` states that its peer check *"does not authenticate a proxy, firewall the
application, or make a proxy sanitize incoming headers."*
[ADR 0184](ARCHITECTURE_DECISIONS/0184-trusted-proxy-scheme.md) warns *"These checks are not peer
authentication."*, and [ADR 0185](ARCHITECTURE_DECISIONS/0185-opt-in-hsts.md) records that
*"Setting the option back to zero stops new headers but does **not** send `max-age=0` or clear a
previously cached HSTS policy."*
`docs/TESTING_STRATEGY.md` records of the HSTS suite that *"It does not verify actual TLS,
browser caching or recovery"* and of the proxy suite that *"It does not test or authenticate a
real proxy chain"*.

So the repository has two opt-in settings, a strip-by-default middleware, a documented assignment of
abuse protection to the edge — and, until this plan, no measurement of what a response from this
application actually carries in either configuration, no contract for cross-origin consumption of
the public API, and no public counterpart to the closed header inventory that exists for the staff
surface.

[ADR 0234](ARCHITECTURE_DECISIONS/0234-network-tls-plan.md) records what this document says and what
it measures. It is not a TLS deployment, not a proxy, not a header policy and not an approval.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat fresh-process sweeps of synthetic responses as a deployment check.
Its prices are counted from the pins and files below, not prototyped: no header, no middleware, no
setting and no dependency was added or reverted to write it.

**Nothing is implemented.** No new header, no new middleware, no new environment variable, no new
dependency, no new control and no new command exists in this tree because of this file. The
profiles below were measured with the configuration this tree already has, in the test process and
in fresh subprocesses, and the temporary probe that took them has been deleted.

## What is true today, measured

Counted on this tree by sweeping responses in two fresh configurations and by reading the settings,
the middleware, the workflow and the documents quoted above. They are pinned by
`daroobank/test_network_tls_plan.py`.

### The two header profiles

* **The route surface is 55 routes: 12 public and 43 staff.** Counted from the live URL resolver in
  one run, matching the sweep sizes `daroobank/test_no_read_audit.py` pins (8×200 and 4×404 for the
  public twelve when health probes are off).
* **Debug-import profile, 13 middleware entries.** A fresh process started with `DAROOBANK_DEBUG=1`
  (the synthetic preview configuration; Django forces `settings.DEBUG` false inside a test run, so
  the profile is named for the import-time configuration that builds the stack). The four public
  HTML responses probed (`/`, `/about/`, `/prices/`, `/search/`) share exactly six headers:
  `content-length`, `content-security-policy`, `content-type`, `cross-origin-opener-policy`,
  `referrer-policy` and `x-content-type-options`; the union over that class adds only
  `cache-control` and `x-robots-tag`, present on `/prices/` (its view sets `noindex, follow`) and
  `/search/` (its view also sets `no-store`) and absent on the two indexable pages. The three API
  responses (`/api/v1/search/`, `/api/v1/products/999999999/`, `/api/v1/openapi.json`) and the two
  handled errors (400 bad cursor, 404 missing presentation) each share exactly eight headers: those
  six plus `cache-control: no-store` and `x-robots-tag: noindex, follow`. The two health probes
  carry the same eight with `x-robots-tag: noindex, nofollow`, disabled as 404 and, with the flag
  on, as 200 `ok` for live and 200 `ok` for ready outside a test transaction — inside one, ready
  answers 503 because `database_ready` refuses an atomic block, which is a property of the test
  harness and not of the probe.
* **Staff profile in the same configuration: 43 routes, anonymous GET.** 41 answers are 302 to the
  login page, 1 is 200 (`/staff/login/`) and 1 is 405 (`/staff/logout/`). Every response carries
  `cache-control: private, no-store, max-age=0`; the class shares ten header names — the public
  eight with `pragma: no-cache` and `vary` added — and the union adds only `allow`, `expires` and
  `location`.
* **Non-debug profile, 14 middleware entries.** A fresh process started with `DAROOBANK_DEBUG=0` and
  a synthetic secret and host. `x-frame-options: DENY` appears on every probed response: all 12
  public routes, the 301 for plain HTTP, and all 43 staff paths, which answer 404 through the
  disabled-portal gate with nine common header names (`cache-control`, `content-security-policy`,
  `content-type`, `cross-origin-opener-policy`, `pragma`, `referrer-policy`,
  `x-content-type-options`, `x-frame-options`, `x-robots-tag`). `strict-transport-security` is
  absent from every response because HSTS is configured at 0 seconds with includeSubDomains false
  and preload false — 0 of 3 HSTS features enabled. Plain HTTP answers 301 to the HTTPS URL.
* **Headers that never appear.** Across every probed response in both configurations:
  `strict-transport-security` (both), `access-control-allow-origin` and every other
  `Access-Control-*` header (both), `cross-origin-resource-policy`, `cross-origin-embedder-policy`
  and `permissions-policy` (both), and `x-frame-options` in the debug-import profile. Cookie flags
  are settings-level facts in these sweeps: `session_secure false` and `csrf_secure false` at
  debug import versus `true` and `true` in non-debug, with `SESSION_COOKIE_HTTPONLY` true and
  `SESSION_COOKIE_SAMESITE` `Lax` in both, and no probed GET set any `Set-Cookie`.

### HSTS, the proxy scheme and the redirect

* **HSTS is 0 of 3.** `SECURE_HSTS_SECONDS` is 0, `SECURE_HSTS_INCLUDE_SUBDOMAINS` is false and
  `SECURE_HSTS_PRELOAD` is false at both import-time debug and non-debug, so no response in either
  profile carried `Strict-Transport-Security`; the opt-in bound the settings accept is 0 through
  31,536,000 seconds, and the flag is ignored in debug.
* **The forwarded scheme is stripped by default.** In a non-debug process without the opt-in, a
  request carrying `X-Forwarded-Proto: https` answered 301 with no HSTS header — the scheme did not
  establish HTTPS. With the opt-in and a trusted peer network, the same request from a trusted peer
  answered 200 (and `max-age=60` when the test set 60 seconds), the same request from an untrusted
  peer answered 301 with no header, and a direct HTTPS request answered 200 with `max-age=60`.
  Turning the flag on without `DAROOBANK_TRUSTED_PROXY_CIDRS` fails startup and names that
  variable. In debug the flag is ignored: the settings dump reads `[true, null, 13]` — debug true,
  `SECURE_PROXY_SSL_HEADER` null, 13 middleware entries.
* **The redirect is non-debug only.** `SECURE_SSL_REDIRECT` is true in non-debug (measured as the
  301 above) and false at debug import.
* **Middleware counts are 13 and 14.** 13 entries at debug import — the count
  `daroobank/test_no_read_audit.py` pins — and 14 in non-debug, where `XFrameOptionsMiddleware` is
  inserted.

### CORS, opener and resource policies, and the referrer split

* **CORS does not exist in this tree.** Non-test `.py` occurrences of `Access-Control`: 0 — no
  module emits it, no CORS middleware is installed, and 0 `Access-Control-*` headers came back on
  any probed response. Before this plan was written the temporary probe (since deleted) also
  counted 0 occurrences in every `.md`, `.html`, `.css`, `.yml` and `.json` file; the only
  documents that name the header now are the plan, its record and the patches quoting this
  measurement, every one of them describing its absence. A browser cross-origin fetch of `api/v1`
  is therefore refused by the same-origin default rather than governed by a policy.
* **`Cross-Origin-Opener-Policy: same-origin` comes from Django's default**, not from this
  repository: `settings.py` never sets `SECURE_CROSS_ORIGIN_OPENER_POLICY`, and the header appears
  on every probed response in both profiles. `Cross-Origin-Resource-Policy`,
  `Cross-Origin-Embedder-Policy` and `Permissions-Policy` are not set by Django and not set here:
  0 occurrences on any probed response.
* **Referrer-Policy is two-speed, 7 of 12.** `no-referrer` on `/search/`, `/api/v1/search/`,
  `/api/v1/openapi.json`, `/products/<pk>/`, `/api/v1/products/<pk>/` and both health probes;
  `same-origin` on `/`, `/about/`, `/prices/`, `/robots.txt` and `/sitemap.xml` — in both
  configurations. Staff responses are always `same-origin`.
* **The CSP is the development policy everywhere, without `frame-ancestors`.** The same
  `default-src 'self' …` string is set by default on every response in both profiles, and
  `daroobank/middleware.py` says *"Do not set frame-ancestors here: development previews embed the
  page"* while non-debug framing is governed by the separately inserted `X-Frame-Options: DENY`.

### The public read limiter and the edge it is not

* **Off by default, in both configurations.** `DAROOBANK_PUBLIC_READ_LIMIT` unset gives
  `PUBLIC_READ_LIMIT_ENABLED` false, and the setting has no DEBUG term — it is the environment
  variable alone that decides. The declared constants are 120 reads per keyed client in a 60-second
  window under the scope `staff_security.public_read.v1`.
* **The refusal shape, measured with the flag forced on and the limit patched to 3:** 200, 200, 200,
  then 429 with `Retry-After: 60` and an empty body; the refusal carries the public privacy headers
  (`cache-control: no-store`, `referrer-policy: no-referrer`, `x-robots-tag: noindex, follow`, the
  development CSP, `cross-origin-opener-policy: same-origin`, `x-content-type-options: nosniff`).
* **The key is a digest, and `X-Forwarded-For` is not read.** One row exists after four reads from
  one `REMOTE_ADDR` even when the request changes `X-Forwarded-For`; the stored key is not the
  address; a second address gets a second row and a 200. `HTTP_X_FORWARDED_FOR` is read by 0
  non-test modules — the only mentions in the tree are test files that send the header.
* **The edge is still where abuse protection belongs.** `docs/DEPLOYMENT.md` says *"Rate and size
  limits still have to be provisioned by the reverse proxy, a CDN or the host before this service
  faces the public internet"*, and the release evidence records that *"no rate limit is on by
  default on any public route, no request-size ceiling is configured and nothing answers 413"*.

### Templates, stylesheets and the workflow

* **63 HTML templates:** 9 in `templates/`, 53 under `templates/staff/` (including the three
  identity partials) and 1 in `templates/partials/`.
* **Two stylesheets:** `static/css/site.css` is 25,166 bytes and `static/css/staff.css` is 8,245
  bytes. `docs/DESIGN_SYSTEM.md` says *"The shared stylesheet `static/css/site.css` is used by
  every current page"* and names *"supplemental `static/css/staff.css`"*.
* **The workflow says nothing about TLS.** `.github/workflows/checks.yml` is 217 lines with 0
  occurrences of `tls`, `hsts` or `proxy` (case-insensitive) and 0 occurrences of `https` or
  `header`: no step fetches a certificate, asserts a header or configures a proxy.

### What the repository already says about it

* `docs/OPERATIONS_RUNBOOK.md` lists, among the readiness report's review conditions, *"HSTS off,
  HTTPS redirection with no trusted proxy header, development hostnames in `ALLOWED_HOSTS`, health
  probes answering, the synthetic login limiter, `XFrameOptionsMiddleware` absent"*.
* `docs/TESTING_STRATEGY.md` states of `daroobank/test_hsts_configuration.py` that *"It does not
  verify actual TLS, browser caching or recovery"* and of `daroobank/test_trusted_proxy_scheme.py`
  that *"It does not test or authenticate a real proxy chain"*.
* [ADR 0210](ARCHITECTURE_DECISIONS/0210-staff-header-inventory.md) sweeps the staff surface to
  *"pin the complete header inventory"* across 1 204 responses; the public surface had no
  counterpart until the profiles above were taken.
* `docs/PHASE1_RELEASE_EVIDENCE.md` describes the limiter as one that *"counts 120 reads per keyed
  client in a rolling minute, refuses an over-limit read with 429 and a `Retry-After`"*.
* Parts of these profiles are already pinned beside this plan: `daroobank/test_no_read_audit.py`
  (the 13-entry middleware tuple and the 12-route public sweep),
  `daroobank/test_content_security_policy.py` (the development CSP without `frame-ancestors`),
  `daroobank/test_public_route_privacy_matrix.py` and `catalog/test_public_read_privacy.py` (the
  public privacy trio on the read routes), `daroobank/test_staff_header_inventory.py` (the closed
  staff set), `daroobank/test_public_read_limit.py` and `daroobank/test_no_abuse_protection.py` (the
  limiter and the absence of abuse protection), and `daroobank/test_environment_documentation.py`
  (the sixteen environment reads).

## Candidate approach and decisions required

The measured starting point is two fresh-process profiles over 55 routes, an HSTS configuration of
0 of 3 features, a forwarded scheme that is stripped unless a reviewed opt-in trusts the peer, no
`Access-Control` header on any response and none in non-test code, a referrer policy that splits
7/12, an opt-in limiter that is off, a workflow that never says TLS, and a closed header inventory
that exists for staff responses only. Everything below is contingent on the decisions it names, and none of them is
answered here.

1. **Which hostnames are approved, and who signs the list?** `require_nondebug_hosts` demands an
   explicit list at startup, but no document names a production hostname.
2. **Who issues and renews the TLS certificate, and what is its shape?** The gate asks for
   *"TLS issuance/renewal"*; nothing in the tree obtains, inspects or renews a certificate, and
   `.github/workflows/checks.yml` has 0 TLS mentions.
3. **Where does TLS terminate, which immediate peers may set `X-Forwarded-Proto`, and who
   overwrites inbound forwarding headers?** The strip-by-default behavior is measured; the topology,
   the peer list and the sanitizing hop are not written down anywhere.
4. **What HSTS value is chosen, and what is the rollback procedure once browsers cache it?**
   [ADR 0185](ARCHITECTURE_DECISIONS/0185-opt-in-hsts.md) records that setting the option back to
   zero *"does **not** send `max-age=0` or clear a previously cached HSTS policy"*; no rollback
   procedure exists in any document.
5. **Which HTTPS, CSRF and cookie checks run against a real deployment, who runs them, and what
   evidence is recorded?** The gate asks for *"HTTPS/CSRF/cookie checks"*; the suites here use
   fresh processes and synthetic values, and the strategy documents record that *"It does not
   verify actual TLS, browser caching or recovery"*.
6. **What isolates the edge, the application and the database, and how is that verified?** The
   gate opens with *"actual network isolation"*; the deployment guide's topology sentence is an
   aspiration, and no verification step exists.
7. **Is cross-origin consumption of the public API meant to stay impossible, and who may add
   `Access-Control-*` headers at a proxy?** Today's answer is the accidental one: 0 such headers
   on any response, 0 occurrences in non-test code, no policy either way, and the OpenAPI contract
   of the public API belongs to another lane and is referenced here rather than priced.
8. **What is the closed header inventory public responses must carry, in debug and in non-debug —
   the public counterpart of the staff inventory?** The profiles above describe what exists; no
   document states what should exist, so a header could be added or lost on the public surface with
   no assertion noticing outside this plan's suite.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the measured edge as it is** | nothing | 0 headers, 0 middleware entries, 0 environment variables, 0 settings and 0 dependencies move; the 13/14 middleware split, the seven-header staff inventory, the public privacy matrices and the default-off HSTS and proxy flags stay exactly as measured | all eight decisions, and whether a tree whose workflow has 0 TLS mentions can satisfy a gate that asks for issuance, renewal and checks |
| **B. Write the target public inventory into documents only** | `docs/DEPLOYMENT.md`, `docs/SECURITY.md` and the evidence row each gain a paragraph naming the headers every public response class must carry | 3 documents reworded; every new link moves the `LINK_COUNT` that `daroobank/test_document_links.py` pins (recounted by running it, never from this plan), and the two gate sentences this plan quotes from the evidence row must survive in place or this plan's suite fails | whether a documented inventory that no test enforces survives the next header change — the staff inventory exists because prose alone did not catch drift |
| **C. Pin the public inventory in a suite of its own** | one new test module sweeping the 12 public routes in both configurations against a closed header list | `TEST_MODULE_COUNT` moves by +1 in `daroobank/test_mfa_implementation_plan.py` and `daroobank/test_secret_rotation_plan.py` (recounted from the tree by running both suites), `docs/TESTING_STRATEGY.md` gains a paragraph, and a `Suite:` line in a record moves the `SUITE_LINE_COUNT` pin if one names it | decisions 4 and 5: a pin proves this tree's behavior, not a certificate, a browser cache or a proxy chain |
| **D. Emit more headers from the application** — for example `Permissions-Policy`, `Cross-Origin-Resource-Policy`, or `frame-ancestors` in the CSP | the development CSP constant and the closed staff inventory both move | `daroobank/test_content_security_policy.py` (5 tests) pins the policy verbatim and asserts `frame-ancestors` is absent; `daroobank/test_staff_header_inventory.py` (6 tests) fails on any header outside its closed set across 1 204 responses; `daroobank/middleware.py`'s frame comment and [ADR 0121](ARCHITECTURE_DECISIONS/0121-development-content-security-policy.md) are contradicted and must be rewritten; the early-redirect and privacy suites re-assert the values | whether the new header suits a preview that embeds itself in iframes and a deployment nobody has run |
| **E. Turn on the existing opt-ins in a deployment** — `DAROOBANK_HSTS_SECONDS`, `DAROOBANK_TRUST_PROXY_SSL_HEADER`, `DAROOBANK_PUBLIC_READ_LIMIT` | no repository file changes: all three exist and are measured off | 0 files, 0 pins and 0 lines move; the cost falls outside the tree — decisions 1–6 stay unanswered while `docs/DEPLOYMENT.md` requires TLS, proxy and rollback review first, and the limiter's window rows still have no pruning command ([ADR 0228](ARCHITECTURE_DECISIONS/0228-public-read-limit.md)) | everything the gate lists: isolation, header sanitization, approved hostnames, issuance and renewal, real HTTPS/CSRF/cookie checks and the HSTS rollback plan |
| **F. Add CORS to the application** — an `Access-Control-Allow-Origin` allowlist for `api/v1` | a setting, its environment variable, and the middleware or view logic that emits the header | one new environment variable costs edits in four pinned places before any behavior exists — `daroobank/test_environment_documentation.py` (8 tests) holds `.env.example`, Compose, the deployment guide and the development guide to exactly the variables the code reads; the 0 non-test occurrences of `Access-Control` this plan measures become a failing assertion; and the OpenAPI contract of the public API is owned by another lane, referenced here and not priced | which origins are trusted, whether credentials ever ride along, and who reviews an allowlist that widens the public API's exposure |
| **G. Declare network and TLS out of Phase 1 scope** | the evidence row stops asking for isolation, hostnames, issuance, checks and rollback, and says what is accepted instead | the row's two quoted gate sentences — pinned by this suite — must be rewritten in place, `docs/DEPLOYMENT.md` and `docs/SECURITY.md` stop asking for TLS in transit, and the readiness report's review list (*"HSTS off, HTTPS redirection with no trusted proxy header"*) loses the conditions it reports | who accepts an edge with no measured certificate, no approved hostname and no rollback plan, which is a decision for an owner and not for this file |

## Required behavior before any production exposure

1. **An approved hostname list exists** and is the same list `require_nondebug_hosts` enforces at
   startup; today the code demands a list and no document names one.
2. **A TLS endpoint with renewal and an incident path exists outside this repository**, and the
   database link's *"`verify-full` for any connection that leaves the host"* posture is reviewed
   with it, not assumed.
3. **The proxy overwrites inbound forwarding headers**, the trusted-peer list is the narrowest
   verified one, and the application is network-restricted so that only that proxy reaches it —
   the deployment guide's own rule: *"the proxy must overwrite incoming forwarding headers,
   preserve the approved Host, and the app must be network-restricted"*.
4. **An HSTS value is chosen together with its rollback procedure**, accounting for clients that
   already cached the policy, because *"Setting the option back to zero stops new headers but does
   **not** send `max-age=0` or clear a previously cached HSTS policy."*
5. **The HTTPS, CSRF and cookie checks the gate asks for are executed against a real deployment**
   and their evidence is recorded; the fresh-process suites cannot substitute, because the
   strategy documents record of them that *"It does not verify actual TLS, browser caching or
   recovery"*.
6. **Edge rate and size limits are provisioned before the service faces the public internet**, as
   `docs/DEPLOYMENT.md` requires: *"Rate and size limits still have to be provisioned by the
   reverse proxy, a CDN or the host before this service faces the public internet"* — the
   application's own limiter is opt-in, off by default, and nothing in the tree answers 413.
7. **The cross-origin contract (decision 7) and the public header inventory (decision 8) are
   decided** before any proxy or patch starts emitting a header this tree has never sent.

## Verification before any enablement

- Re-run both profiles — a fresh process with `DAROOBANK_DEBUG=1` and one with `DAROOBANK_DEBUG=0`
  — over the 12 public routes, the 3 API routes and the 43 staff routes, and re-derive every count
  in this document rather than trusting it: the six- and eight-header public classes, the ten-header
  staff class, the 41/1/1 staff statuses, the 13/14 middleware split, the 7/5 referrer split and the
  set of headers that never appear.
- Re-run the HSTS, proxy and limiter measurements: 0 of 3 HSTS features, the 301/200/301/200
  strip-and-honor matrix, startup failing without `DAROOBANK_TRUSTED_PROXY_CIDRS`, the
  200/200/200/429 sequence with `Retry-After: 60`, and the one-row-per-address key behavior with
  `X-Forwarded-For` changing nothing.
- Re-count the static facts: 63 templates, 25,166 and 8,245 stylesheet bytes, 0 non-test
  occurrences of `Access-Control`, 0 non-test reads of `HTTP_X_FORWARDED_FOR`, and
  `.github/workflows/checks.yml` still at 217 lines with 0 TLS, HSTS or proxy mentions.
- Run `daroobank/test_network_tls_plan.py`, `daroobank/test_document_links.py`,
  `daroobank/test_mfa_implementation_plan.py` and `daroobank/test_secret_rotation_plan.py`, and take
  every global pin this plan moves from their failure messages instead of from this document.
- Confirm that no header, middleware, environment variable, dependency, model or command has
  appeared while this plan claims none has, and re-run that confirmation after any later edit to
  this file or its record.
- Record named owners and evidence for network, security and release approval. No production
  enablement, no TLS deployment, no header policy and no Phase 1 completion follows from this plan
  or its suite.
