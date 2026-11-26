# 0211 — A caller-supplied `next` cannot aim the staff surface off-host

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_staff_redirect_targets.py` (8 tests, ~15 s)
Companion: 0200 (authorization matrix), 0209 (method sweep), 0210 (header inventory)

## Context

The staff surface has exactly one response field whose value is taken straight from
the request and handed back to the browser as a navigation target: the `Location`
header of a 302. It appears in three places — the login redirect after a successful
POST, the logout redirect, and the `login_required`-style redirect that every one of
the 41 matrix routes emits for an anonymous caller. ADR 0210 pinned that a 302
points at the staff login or at `home` for the *swept* requests, but those requests
carried no caller-controlled `next`, so the interesting case was untested.

Django defends this with `RedirectURLMixin.get_redirect_url()`, which passes the
value through `url_has_allowed_host_and_scheme` with `allowed_hosts={request.get_host()}`
and falls back to `get_default_redirect_url()` when the check fails. This project
overrides that default in `pricing/staff_views.py::StaffLoginView` to send an active
staff account to `reverse('staff_workspace')` (`/staff/`), and `StaffLogoutView` sets
`next_page = 'home'`. None of that was asserted anywhere: a future refactor that
read `request.GET['next']` directly would have turned every staff login into an open
redirect and no test would have noticed.

## Decision

Probe both authentication endpoints and all 41 matrix routes with **21 caller-supplied
targets** — 12 hostile, 8 that Django's validator accepts, and the empty string — and
pin the exact outcome for each.

**Hostile values** (protocol-relative `//evil.example/` and `///evil.example/`,
`https://` and `http://`, the single-slash `https:/evil.example`, the backslash forms
`/\evil.example/` and `\\evil.example`, `javascript:alert(1)`, a `data:` URL, embedded
userinfo `https://user@evil.example/`, an upper-cased scheme, and a leading-space
variant):

- **Login POST with valid credentials** → 302 to `/staff/`, the overridden default.
  Never to the supplied value; the emitted `Location` has no scheme, no netloc, no
  leading `//` and no `evil.example` in its path.
- **Login POST with a wrong password** → 200 form, no `Location` header at all, so a
  failed attempt cannot be used to redirect anyone.
- **Logout POST** → 302 to `/` (`next_page = 'home'`). Logout answers **405** to a GET
  with the same parameter, so a link a user merely clicks cannot log them out and send
  them somewhere.
- **Anonymous GET on any of the 41 matrix routes** → 302 whose path is exactly
  `/staff/login/`, with no netloc, and whose own `next` parameter decodes to the
  *requested staff URL* — the hostile value survives only as a query parameter of that
  staff URL (`/staff/sources/1/?next=https%3A%2F%2Fevil.example%2F`), never as the
  target. 12 × 41 = 492 such redirects are checked individually.
- **Following the chain** (`follow=True`) from eight representative routes plus both
  endpoints: every hop is a relative same-host path and the final status stays inside
  `{200, 302, 400, 403, 404, 405, 409}`.
- **The login form echoes only the validated target.** `LoginView.get_context_data`
  puts `get_redirect_url()` — not the raw parameter — into the template context, so
  `templates/staff/login.html`'s hidden `next` input renders **empty** for all 12
  hostile values and renders the accepted value otherwise, HTML-escaped by autoescape.
  `<script>alert(1)</script>` never appears unescaped in the page.

**Field-name and precedence abuse:** eight other plausible parameter names
(`return_to`, `redirect`, `returnUrl`, `next_page`, `continue`, `url`, `target`,
`destination`) are ignored — the login still goes to `/staff/`. A duplicated query
parameter resolves to its **last** value, so `?next=/staff/&next=https://evil.example/`
lands on the default, not on the safe first value; and a `next` in the request body
wins over one in the query string.

**What is honoured, recorded rather than assumed:** eight values pass Django's check and
are emitted verbatim (after `iri_to_uri`): `/`, `/staff/prices/`, the relative
`staff/prices/`, the percent-encoded `/%2f%2fevil.example/`, the traversal form
`/staff/../../evil`, the encoded scheme `https%3A%2F%2Fevil.example%2F`, a nested
`/staff/prices/?next=https://evil.example/`, and `"><script>alert(1)</script>` — the
last one appearing in the `Location` header as
`%22%3E%3Cscript%3Ealert(1)%3C/script%3E` because `HttpResponseRedirect` IRI-encodes
its target, so HTML metacharacters cannot reach a header raw. Every one of these keeps
`netloc` empty.

The probe writes nothing: the 14 counted write and audit models hold the same row
counts afterwards.

## Red check

Replacing `StaffLoginView`'s inherited validator with a naive
`get_redirect_url` that returns `request.POST.get('next') or request.GET.get('next')`
produces **25 failures**: 12 in `test_a_hostile_next_never_becomes_the_login_target`,
12 in `test_the_login_form_echoes_only_a_validated_target` and 1 in
`test_only_the_next_field_controls_the_target`. The override was removed from
`pricing/staff_views.py` and `git diff --stat` is empty.

## Limitations

- The check is `allowed_hosts={request.get_host()}`, so **whatever the deployment
  accepts as a `Host` header becomes an allowed redirect target**. `ALLOWED_HOSTS`
  under the synthetic settings includes `testserver` and `.e2b.app`; a misconfigured
  production `ALLOWED_HOSTS` or a proxy that forwards an attacker-chosen `Host` would
  widen this suite's notion of "same host" without any test here failing. Host-header
  trust is covered by the non-debug startup checks and `TrustedProxySchemeMiddleware`,
  not by this suite.
- `require_https=self.request.is_secure()` is `False` for these plain-HTTP test
  requests, so an `http://` target for the *same* host would be accepted. No HTTPS
  upgrade of redirect targets is asserted.
- The percent-encoded `/%2f%2fevil.example/` is emitted unchanged. Python's `urlsplit`
  does not decode `%2F`, so Django's validator sees a same-host path; a proxy or
  backend that normalizes `%2F` to `/` before routing could reinterpret it. This is
  recorded as observed behavior, not proven safe.
- Relative targets without a leading slash (`staff/prices/`) are emitted as-is, which
  a browser resolves against the current path (`/staff/login/` → `/staff/staff/prices/`).
  Same-host, but not the URL the caller meant; no normalization is asserted.
- Only `next` on the two authentication endpoints and on anonymous route redirects is
  probed. Views that build their own redirect from other parameters (for example a
  filter that echoes state into a URL) are not covered here, and `ROUTES` is the
  resolver-derived matrix from ADR 0200, so a new staff route joins the sweep only if
  it joins that matrix.
- Body values are sent as form-encoded POST data. A JSON body, a multipart body or a
  `next` inside a cookie is not probed.
