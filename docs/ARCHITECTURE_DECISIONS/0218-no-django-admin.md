# 0218 — no `django.contrib.admin`: the staff portal is the only administrative surface

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_no_django_admin.py` (7 tests, ~1.1 s)

## Context

[The roadmap](../ROADMAP.md) lists an "auth/admin baseline" among the Phase 1 deliverables
and [the technology decision record](../TECH_STACK_DECISIONS.md) names Django's admin as one
of the reasons to pick Django. The implementation never installed it. Nothing recorded that
choice, so it looked like an omission rather than a decision — and an omission is the kind
of thing that gets "fixed" later by adding one line to `INSTALLED_APPS`.

What the project built instead is a hand-made staff portal: 43 routes whose authorization,
denial parity, identifier and method parity, query parity, CSRF gate, session lifecycle,
header inventory, redirect targets and durable session invalidation are each measured by a
pinned suite (ADRs 0199–0217), collected in the generated
[authorization review](../AUTHORIZATION_REVIEW.md).

Installing `django.contrib.admin` would add a second administrative surface next to that
one: its own login, logout and password-change routes, its own permission behavior driven
mostly by `is_superuser`, a `django_admin_log` table it writes to, a route per registered
model per action, and none of the measurements above. It would also change the public
request path: Django's own system checks refuse to start the admin unless
`django.contrib.auth.context_processors.auth` and
`django.contrib.messages.context_processors.messages` are enabled in `TEMPLATES`, which
means every template render in the application, public pages included.

## Decision

Keep `django.contrib.admin` out of `INSTALLED_APPS`, keep the admin unmounted, and pin the
absence with `daroobank/test_no_django_admin.py` so that adding it is a deliberate act that
breaks seven tests and requires its own decision record.

Two supporting changes were needed to make the drift guard honest:

- `daroobank/authorization_review.py` used to read route names from the top level of the
  resolver, which raises `AttributeError` on a `URLResolver` — exactly what a mounted
  `include()` produces. It now walks nested resolvers, and `public_rows()` reports a
  non-staff route with no probe row as uncovered (`probes: 0`, `statuses: none`) instead of
  raising `KeyError`. The generated review is byte-identical for the current flat URLconf;
  the change only affects what happens when a second surface appears.
- The "no third surface" assertion takes its public set from the ADR 0202 probe matrix, not
  from the walked inventory. Deriving it from the inventory would let a newly mounted
  surface define itself as public and the check would pass.

## Measured behavior

| Measurement | Result |
|---|---|
| Installed apps | exactly `auth`, `contenttypes`, `sessions`, `staticfiles`, `catalog`, `pricing`, `sources`, `ingestion`, `clinical`, `staff_security`, `daroobank`; no app label or name containing `admin` |
| `/admin/`, `/admin`, `/admin/login/`, `/admin/logout/`, `/admin/auth/user/`, `/admin/catalog/productcandidate/`, `/admin/password_change/` | all `Resolver404`, with `/staff/login/` resolving as the positive control |
| `GET /admin/` and `GET /admin/login/` | 404 for an anonymous caller and for a logged-in superuser, byte-identical, a 179-byte plain "Not Found" page containing no `administrator`, `Django admin`, `Log in`, `csrfmiddlewaretoken` or `username` marker |
| Database | the only `django_*` tables are `django_content_type`, `django_migrations` and `django_session`; no table matching `%admin%`; 32 tables in total, the inventory ADR 0216 pins |
| Imports | no module in the seven project packages imports `django.contrib.admin`, checked by parsing the AST rather than searching text (so this suite's own prose does not count), with a positive control that the same scan does find `django.contrib.sessions` imports |
| Resolver surface | every named route, walking nested resolvers, is one of the 43 `staff_*` routes or one of the 12 routes the privacy matrix probes; nothing else |
| Operational commands | `check_deployment_readiness` (daroobank), `cleanup_staff_login_windows`, `list_staff_sessions`, `revoke_staff_sessions` (staff_security) and `inspect_postgresql_schema` (catalog) are all registered |

## Red check

Installing `django.contrib.admin` and `django.contrib.messages`, adding the messages
middleware and the two template context processors Django's checks demand, and mounting
`path('admin/', admin.site.urls)` fails **all 7** tests in this suite — the app-label list,
six admin paths that now resolve, the 404 that becomes a redirect to an admin login page,
the `django_admin_log` table that appears, the `from django.contrib import admin` import in
`urls.py`, and the third surface in the resolver — plus **3** in the review drift suite,
because the generated tables no longer match the resolver. Without the context processors
the suite never runs at all: `manage.py test` stops at `admin.E402` and `admin.E404`.
Everything was restored from backups and both suites returned to green.

## Limitations

- **This pins an absence; it is not a review of the staff portal.** That the admin is not
  installed says nothing about whether the 43 routes that replace it are adequate, and the
  review document's judgement is still unsigned.
- The app-label assertion fails on *any* installed-app change, including a legitimate one.
  That is deliberate — a new app is a new surface — but it means the test must be edited
  whenever the project grows an app, and the edit is where the judgement lives.
- The AST scan detects imports in project source. It cannot see `importlib` loading at
  runtime, an app added by a third-party package, or an admin mounted from another
  URLconf that is itself included later.
- The 179-byte assertion pins the current not-found page. A template change breaks it,
  which is a reminder to re-check what a 404 says, not a security property in itself.
- Not installing the admin also gives up `django_admin_log`. The domain review rows record
  who staged and reviewed each candidate, and ADRs 0192–0199 recheck the actor inside those
  writes, but there is no general administrative change log; that gap belongs to the data
  and clinical governance gate, and this ADR does not close it.
- If an admin surface is ever wanted — for content editors, for support tooling — it needs
  its own decision record, its own authorization measurement and an update to this suite.
  Nothing here argues that it could never be acceptable.
