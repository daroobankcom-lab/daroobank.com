"""Generated tables for the endpoint-by-endpoint authorization review document.

The Phase 1 gate asks for a complete endpoint-by-endpoint authorization review. The
judgement in that review needs owners; the *inventory* it has to be based on does not,
and an inventory typed by hand goes stale. So the two tables in
`docs/AUTHORIZATION_REVIEW.md` are derived from the code instead:

* the live URL resolver, for route names and URL patterns;
* `test_staff_authorization_matrix.ROUTES`, for the requirement each staff route declares;
* `test_staff_method_sweep` and `test_staff_csrf_gate`, for the methods each route's
  decorators actually allow;
* `test_staff_write_route_inventory`, for which routes write and which synchronized
  in-flight test covers them;
* `test_public_route_privacy_matrix.PUBLIC_ROUTES`, for the non-staff surface and the
  statuses its probes expect.

`daroobank/test_authorization_review_drift.py` re-renders these tables and compares them
with the document, so the review cannot drift from what the resolver serves.

Regenerate with:

    . .cache/pg-local.env && .venv/bin/python -c "import os, django; \\
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'daroobank.synthetic_test_settings'); \\
        django.setup(); from daroobank.authorization_review import render_review; \\
        print(render_review())"

This is an inventory of what is enforced and where it is measured. It is not a review,
not a threat model and not an approval: nothing here establishes that a requirement is
the right one, that the routes are the right routes, or that the surface may be exposed.
"""
from collections import Counter

from django.urls import get_resolver

from .test_public_route_privacy_matrix import PUBLIC_ROUTES
from .test_staff_authorization_matrix import AUTH_ROUTES, ROUTES, STAFF_ONLY
from .test_staff_csrf_gate import DUAL_METHOD_ROUTES, POST_ONLY_ROUTES
from .test_staff_method_sweep import EXPECTED_ALLOW
from .test_staff_write_route_inventory import COVERED_WRITE_ROUTES, NON_WRITE_ROUTES

BEGIN = '<!-- GENERATED BEGIN: python -m daroobank.authorization_review -->'
END = '<!-- GENERATED END -->'

AUTH_REQUIREMENT = {
    'staff_login': 'none — this is the entry point; a successful POST binds a session',
    'staff_logout': 'an authenticated session; POST only',
}
# The ADR 0200 matrix deliberately excludes the two authentication endpoints, and the
# ADR 0213 guard measures the other 41 routes plus the binding that happens at login, so
# the evidence for these two is listed explicitly rather than inherited.
# `AUTH_ROUTES` is a frozenset, and set iteration order depends on the interpreter's
# hash seed, so the generated block would render these two rows in either order between
# runs. The document is a byte-for-byte comparison target: order it explicitly.
AUTH_ORDER = ('staff_login', 'staff_logout')
AUTH_EVIDENCE = {
    'staff_login': '0207, 0208, 0209, 0210, 0211, 0212, 0213 (bound here)',
    'staff_logout': '0207, 0208, 0209, 0210, 0211, 0212',
}
# Evidence every staff route carries, from the suites that sweep all of them.
BASE_EVIDENCE = ('0200', '0206', '0207', '0208', '0209', '0210', '0213')
OBJECT_EVIDENCE = ('0201', '0204', '0205')


def _walk(resolver, prefix=''):
    """Yield (name, pattern) for every route below a resolver, including nested ones.

    A mounted ``include()`` — the Django admin, or any app that ships its own URLs — puts a
    ``URLResolver`` among the top-level patterns, and a resolver has no ``name``. Walking
    keeps the inventory complete instead of raising, which is what a drift guard is for.
    """
    for entry in resolver.url_patterns:
        if hasattr(entry, 'url_patterns'):
            yield from _walk(entry, prefix + str(entry.pattern))
        elif entry.name is not None:
            yield entry.name, prefix + str(entry.pattern)


def patterns():
    """Map every named route to the URL pattern the resolver serves for it."""
    return dict(_walk(get_resolver()))


def route_names():
    """Every named route the resolver serves, wherever it is mounted."""
    return set(patterns())


def group_of(name):
    if name in AUTH_ORDER:
        return name
    if name in POST_ONLY_ROUTES:
        return 'post-only'
    if name in DUAL_METHOD_ROUTES:
        return 'dual'
    return 'safe-only'


def methods_text(name):
    return EXPECTED_ALLOW[group_of(name)]


def requirement_text(requirement):
    if requirement == STAFF_ONLY:
        return '`is_staff`, no specific permission'
    kind, *permissions = requirement
    joined = ', '.join(f'`{permission}`' for permission in permissions)
    return f'{kind} of {joined}'


def write_text(name):
    if name in COVERED_WRITE_ROUTES:
        return f'yes — `{COVERED_WRITE_ROUTES[name]}`'
    return f'no — {NON_WRITE_ROUTES[name]}'


def evidence_text(name, kwargs):
    if name in AUTH_ROUTES:
        return AUTH_EVIDENCE[name]
    evidence = list(BASE_EVIDENCE)
    if kwargs:
        evidence += list(OBJECT_EVIDENCE)
    if name in COVERED_WRITE_ROUTES:
        evidence += ['0192–0199']
    return ', '.join(evidence)


def display_pattern(pattern):
    """Render a URL pattern for the table; the root route's pattern is an empty string."""
    return pattern if pattern else '(site root)'


def staff_rows():
    """Yield one row per staff route the resolver serves, in matrix order."""
    urls = patterns()
    for name, kwargs, _method, requirement in ROUTES:
        yield {
            'name': name, 'pattern': display_pattern(urls[name]), 'methods': methods_text(name),
            'requirement': requirement_text(requirement), 'writes': write_text(name),
            'evidence': evidence_text(name, kwargs),
        }
    for name in AUTH_ORDER:
        yield {
            'name': name, 'pattern': display_pattern(urls[name]), 'methods': methods_text(name),
            'requirement': AUTH_REQUIREMENT[name], 'writes': write_text(name),
            'evidence': evidence_text(name, {}),
        }


def public_rows():
    """Yield one row per non-staff route, with the probes that cover it."""
    urls = patterns()
    probes = Counter(name for _label, name, _kwargs, _query, _status in PUBLIC_ROUTES)
    statuses = {}
    for _label, name, _kwargs, _query, status in PUBLIC_ROUTES:
        statuses.setdefault(name, set()).add(status)
    for name, pattern in urls.items():
        if name.startswith('staff_'):
            continue
        # A non-staff route with no probe row is reported as uncovered rather than
        # raising: the review's job is to show the gap, and the drift test rejects it.
        yield {
            'name': name, 'pattern': display_pattern(pattern), 'probes': probes.get(name, 0),
            'statuses': ', '.join(str(status) for status in sorted(statuses.get(name, ()))) or 'none',
            'evidence': '0202' if name in probes else 'none',
        }


def render_review():
    """Render the generated block, between the markers the drift test looks for."""
    staff = list(staff_rows())
    public = list(public_rows())
    lines = [
        BEGIN,
        f'Counts derived from the live resolver: **{len(staff)} staff routes** and '
        f'**{len(public)} non-staff routes**, {len(PUBLIC_ROUTES)} public probe rows.',
        '',
        '## Staff routes',
        '',
        'Requirement columns are what the route declares; the evidence columns are the ADRs whose suites measure it.',
        '',
        '| Route | URL pattern | Allowed methods | Requirement | Writes | Evidence |',
        '|---|---|---|---|---|---|',
    ]
    for row in staff:
        lines.append(f"| `{row['name']}` | `{row['pattern']}` | `{row['methods']}` | {row['requirement']} "
                     f"| {row['writes']} | {row['evidence']} |")
    lines += [
        '',
        '## Non-staff routes',
        '',
        'Every one of these is probed anonymously and as a fully permitted staff account for private-data leakage; '
        'the statuses column is what those probes expect today.',
        '',
        '| Route | URL pattern | Probe rows | Expected statuses | Evidence |',
        '|---|---|---|---|---|',
    ]
    for row in public:
        lines.append(f"| `{row['name']}` | `{row['pattern']}` | {row['probes']} | {row['statuses']} "
                     f"| {row['evidence']} |")
    lines.append(END)
    return '\n'.join(lines)


REVIEW_PATH = 'docs/AUTHORIZATION_REVIEW.md'


def write_review(path=REVIEW_PATH):
    """Replace the generated block in the review document with a fresh render.

    Returns the number of characters written, or raises when the markers are missing,
    because a document without them cannot be updated without destroying its prose.
    """
    from pathlib import Path

    target = Path(path)
    text = target.read_text(encoding='utf-8')
    current = generated_block(text)
    if current is None:
        raise ValueError(f'{path} has no generated block; refusing to rewrite it.')
    fresh = render_review()
    target.write_text(text.replace(current, fresh), encoding='utf-8')
    return len(fresh)


def generated_block(document):
    """Return the generated block inside a document, or None when the markers are absent."""
    if BEGIN not in document or END not in document:
        return None
    return document[document.index(BEGIN):document.index(END) + len(END)]
