# 0223 — abuse protection is external: what the application limits, and what it does not

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_no_abuse_protection.py` (10 tests, ~1.1 s)

## Context

`docs/SECURITY.md` lists rate limits among the controls this product is supposed to have, and its
upload section says the application's size check happens after Django has received the request.
Neither claim was measured, and the difference between "the platform will protect this" and
"nothing here protects this" is what an operator has to know before this service faces the public
internet — including a reachable development preview, which is what the staff portal already is
in debug mode.

There was also no place that said who is responsible. `docs/DEPLOYMENT.md` asked for TLS, secure
headers, backups, monitoring and access review in its release gates, and mentioned "polling
limits" once in passing for the health probes, but never named rate limiting or request size.

## Decision

Measure what the application limits and what it does not, pin that shape with
`daroobank/test_no_abuse_protection.py`, and add an "Abuse protection is external" section to
`docs/DEPLOYMENT.md` that assigns the rest to the edge. No limiter was added: choosing rates,
client identity and storage for a limiter is a design decision with a proxy topology and a
privacy dimension that this project has not made, and the one limiter it does have (ADR 0181) is
explicitly a development control.

## Measured behavior

| Measurement | Result |
|---|---|
| Rate limiting in project code | the literal `429` appears in exactly one non-test module, `pricing/staff_views.py`; `Retry-After` appears in none; `staff_security.throttle` is imported by exactly one non-test module; no project class has a limiter-like name; the twelve-entry `MIDDLEWARE` ADR 0221 pins contains no limiter |
| Opt-in state | `STAFF_LOGIN_THROTTLE_ENABLED` is `False` in the synthetic environment, and is computed as `DEBUG and DAROOBANK_STAFF_LOGIN_THROTTLE == '1'`, so it cannot be on in a non-debug deployment |
| The limiter's four outcomes | with the flag forced on and `consume_attempt` patched: `limited` → **429**, `text/plain; charset=utf-8`, no rate-limit header and no `csrfmiddlewaretoken` in the body; `unavailable` → **503**, no rate-limit header; `allowed` → 200 login form with a CSRF token and exactly one consume call; flag off → `consume_attempt` is never called and the form answers 200 |
| Public reads | six routes — home, about, price list, search, search API, OpenAPI document — read eight times each by one anonymous client: **48 requests, all 200**, none carrying `Retry-After`, `X-RateLimit-*`, `X-Rate-Limit-*` or `RateLimit-*`, every one carrying `content-security-policy` as the positive control that the header inspection sees headers at all |
| Rows written by those reads | none: all 23 project table counts unchanged (the counter ADR 0221 uses, whose positive control is that it sees an insert) |
| Request-size ceiling | `settings.py` defines neither `DATA_UPLOAD_MAX_MEMORY_SIZE` nor `FILE_UPLOAD_MAX_MEMORY_SIZE`; both are Django's default 2621440; no project module contains `413` |
| Upload limits that do exist | `catalog.intake.MAX_FILE_BYTES` is 1 MiB and `pricing.importer.MAX_FILE_BYTES` is 2 MiB, enforced as `file.size > MAX_FILE_BYTES` / `upload.size > MAX_FILE_BYTES` in forms — that is, on a body Django has already spooled |
| An oversized upload | an authorized stager POSTing a 2 MiB + 1 KiB CSV to `/staff/prices/import/` gets **200** with `form.errors['csv_file']`, no `PriceCandidate` row and no rate-limit header: refused by validation, not by a transport ceiling |

## Red check

Six regressions, each applied alone and reverted:

| Regression | Failures |
|---|---|
| `RATE_LIMIT_STATUS = 429` appended to `catalog/views.py` | the single-`429` pin named two modules |
| `headers={'Retry-After': '60'}` added to the login 429 | two failures: the `Retry-After` absence pin and the behavioral assertion on the 429 response |
| `DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024` added to `settings.py` | the ceiling pin failed |
| `from staff_security.throttle import consume_attempt` added to `sources/staff_views.py` | the single-call-site pin named two modules |
| A `RateLimitHeaderMiddleware` added to `daroobank/middleware.py` and to `MIDDLEWARE` | 53 failures: the middleware pin, the limiter-class pin, both login-limiter responses, the oversized upload and every one of the 48 public reads |
| The new `docs/DEPLOYMENT.md` section deleted | three assertions about the guide failed |

An earlier attempt at the second red check did not apply at all — a shell quoting error left the
file unchanged and the suite passed — and was redone with the patch asserted before the run. A red
check whose patch did not apply measures nothing, so each of the six was verified by the failure
it produced.

## Limits

- This pins what happens **inside the process**. A reverse proxy, CDN, WAF, firewall or host-level
  control would be invisible here, and `docs/DEPLOYMENT.md` now says one is required without
  arranging it.
- The code-level pins are literal and AST based. A limiter written as
  `status=HTTPStatus.TOO_MANY_REQUESTS`, or provided by a third-party package, would not match the
  `429` scan; the middleware pin, the class-name pin and the 48-request sweep would still catch a
  limiter that actually refuses or marks requests.
- The sweep is not a load test. It is one in-process client making 48 sequential requests, which
  shows that nothing refuses or records a read; it says nothing about throughput, latency or
  behavior under real concurrency, and nothing about a slow-client or connection-exhaustion
  attack.
- Only the price upload is exercised behaviorally. The 1 MiB product-intake limit is pinned
  structurally, and neither limit is tested against a real multi-gigabyte body — the point of the
  measurement is that Django has already spooled whatever arrives.
- The absence of `Retry-After` is pinned as a fact about today, not as a virtue. Adding the header
  to the login 429 would be an improvement for clients and would fail this suite until this record
  is updated. [ADR 0228](0228-public-read-limit.md) added an opt-in public read limiter that does
  send the header, and moved the pins in this record's suite; the login 429 still sends none.
- Whether the current limits are right — ten login attempts per minute per client key, 2 MiB for a
  price CSV, 1 MiB for a product file — is not judged anywhere here.
