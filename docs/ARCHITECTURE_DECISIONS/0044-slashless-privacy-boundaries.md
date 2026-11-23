# ADR 0044: privacy boundaries for known slashless paths

Status: development implementation, 23 November 2026.

## Context and decision

Django's `CommonMiddleware` may redirect a slashless URL to its slash-terminated route before setting `request.resolver_match`. Public search and product reads already have a restrictive no-store, no-referrer, noindex policy for resolved requests, but those redirects previously did not. The slashless staff root `/staff` similarly fell outside the staff-path guard, so it could redirect to `/staff/` even when the portal was disabled.

The public privacy middleware now also recognizes exactly `/search`, `/api/v1/search`, `/products/<ASCII digits>` and `/api/v1/products/<ASCII digits>` without the trailing slash, including when `APPEND_SLASH` is disabled. It sets the same headers as on the corresponding resolved endpoints. It does not change redirects, URL parsing, responses or the published catalog. The staff middleware recognizes `/staff` as well as `/staff/` descendants: the disabled portal returns its existing generic 404, and the enabled portal retains its usual redirect with private headers. Similar prefixes, such as `/staffing`, are not staff paths.

## Evidence and limitations

Synthetic tests cover GET and HEAD redirects with a query canary, disabled slash appending, exact path boundaries, disabled/enabled staff root, and unchanged lookalike routes. The redirect still carries the original query in its `Location`; headers do not remove it from browser history, server or proxy logs, monitoring, or all intermediaries. The same-origin staff referrer policy preserves Django's HTTPS CSRF referer behavior and is not a blanket no-referrer policy. An outer response-only middleware now also adds the corresponding known-path headers to Django's early HTTPS redirects, without changing the HTTPS redirect or disabled staff gate order. Reverse proxies, other unresolved paths, non-Django responses and infrastructure logging remain outside these controls. These measures are not a production security assessment or a substitute for deployment privacy and access controls.
