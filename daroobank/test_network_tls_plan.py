"""The network and TLS plan is a proposal, its numbers are measured, and nothing is implemented.

`docs/NETWORK_TLS_PLAN.md` exists because `docs/PHASE1_RELEASE_EVIDENCE.md` carries *\"actual
network isolation, trusted proxy configuration and header sanitization, approved hostnames, TLS
issuance/renewal, HTTPS/CSRF/cookie checks and HSTS rollback plan\"* as an open gate while this
repository contains two opt-in settings, a strip-by-default middleware and no measurement of what a
response actually carries in either configuration, no contract for cross-origin consumption of the
public API, and no public counterpart to the closed header inventory ADR 0210 pins for staff
responses. This suite holds the plan to four properties.

It has to stay a proposal: nothing may be implemented while it claims nothing is. It has to cite
the requirements it is written against, so the plan cannot drift away from the deployment guide,
the security document, the settings comments or the records that measured the opt-ins. Its numbers
have to be the measured ones — the two header profiles, the HSTS and proxy matrices, the referrer
split, the limiter's refusal shape, the template, stylesheet and workflow counts — and the tree
itself has to keep matching them: the settings shape, the database-free public responses and the
static counts are re-measured here rather than trusted from the document. And the neighbour
documents and the evidence row have to link the plan and its record.

What is not checked is whether the eight decisions should be answered the way any particular reader
would answer them, whether a certificate, a proxy or a browser cache behaves as these fresh-process
sweeps suggest, or who may approve an edge. Those are decisions for named owners, and no test can
make them.
"""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import Client, SimpleTestCase
from django.urls import get_resolver, reverse

from staff_security import read_limit

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'NETWORK_TLS_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0234-network-tls-plan.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
DESIGN = ROOT / 'docs' / 'DESIGN_SYSTEM.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
MIDDLEWARE = ROOT / 'daroobank' / 'middleware.py'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
REQUIREMENTS_IN = ROOT / 'requirements.in'
REQUIREMENTS = ROOT / 'requirements.txt'
ADR_0121 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0121-development-content-security-policy.md'
ADR_0184 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0184-trusted-proxy-scheme.md'
ADR_0185 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0185-opt-in-hsts.md'
ADR_0210 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0210-staff-header-inventory.md'
ADR_0228 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0228-public-read-limit.md'

SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before any production exposure',
            'Verification before any enablement']
SUBSECTIONS = ['The two header profiles',
               'HSTS, the proxy scheme and the redirect',
               'CORS, opener and resource policies, and the referrer split',
               'The public read limiter and the edge it is not',
               'Templates, stylesheets and the workflow',
               'What the repository already says about it']
DECISIONS = ['Which hostnames are approved, and who signs the list?',
             'Who issues and renews the TLS certificate, and what is its shape?',
             'Where does TLS terminate, which immediate peers may set `X-Forwarded-Proto`, and who '
             'overwrites inbound forwarding headers?',
             'What HSTS value is chosen, and what is the rollback procedure once browsers cache it?',
             'Which HTTPS, CSRF and cookie checks run against a real deployment, who runs them, and '
             'what evidence is recorded?',
             'What isolates the edge, the application and the database, and how is that verified?',
             'Is cross-origin consumption of the public API meant to stay impossible, and who may '
             'add `Access-Control-*` headers at a proxy?',
             'What is the closed header inventory public responses must carry, in debug and in '
             'non-debug — the public counterpart of the staff inventory?']
OPTIONS = ['A. Leave the measured edge as it is',
           'B. Write the target public inventory into documents only',
           'C. Pin the public inventory in a suite of its own',
           'D. Emit more headers from the application',
           'E. Turn on the existing opt-ins in a deployment',
           'F. Add CORS to the application',
           'G. Declare network and TLS out of Phase 1 scope']
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'must not be read as a decision',
                    'the temporary probe that took them has been deleted',
                    'No new header, no new middleware, no new environment variable']
# Words that would make the plan choose rather than price: none may appear in it.
FORBIDDEN_SELECTION = ['The selected approach is to', 'is selected because',
                       'the recommended approach', 'should be adopted',
                       'The selected option is']
# The requirement each document states, quoted into the plan and pinned here, so the plan cannot
# drift away from the sentences it is written against.
QUOTED_REQUIREMENTS = [
    (EVIDENCE, 'Optional proxy-scheme trust and HSTS settings exist; both are off by default.'),
    (EVIDENCE, 'actual network isolation, trusted proxy configuration and header sanitization, '
               'approved hostnames, TLS issuance/renewal, HTTPS/CSRF/cookie checks and HSTS '
               'rollback plan; see ADRs 0184–0185.'),
    (EVIDENCE, 'counts 120 reads per keyed client in a rolling minute, refuses an over-limit read '
               'with 429 and a `Retry-After`'),
    (EVIDENCE, 'no rate limit is on by default on any public route, no request-size ceiling is '
               'configured and nothing answers 413'),
    (DEPLOYMENT, 'HSTS is off unless `DAROOBANK_HSTS_SECONDS` is explicitly set to a positive '
                 'value outside debug.'),
    (DEPLOYMENT, 'The application does not enable subdomain inclusion or preload; an upstream '
                 'proxy may independently set HSTS.'),
    (DEPLOYMENT, 'The flag is off by default and ignored in debug.'),
    (DEPLOYMENT, '**not** a firewall or proof that the peer is an authorized proxy: the proxy must '
                 'overwrite incoming forwarding headers, preserve the approved Host, and the app '
                 'must be network-restricted'),
    (DEPLOYMENT, 'Rate and size limits still have to be provisioned by the reverse proxy, a CDN or '
                 'the host before this service faces the public internet'),
    (DEPLOYMENT, '`verify-full` for any connection that leaves the host, so the server certificate '
                 'is checked and the link is encrypted in transit'),
    (SECURITY, 'TLS in transit; encryption at rest where appropriate with isolated managed keys '
               'and rotation; least-privilege DB/worker credentials.'),
    (SETTINGS, 'HSTS is off until an operator explicitly selects a reviewed TLS policy.'),
    (SETTINGS, 'Disabled by default and in debug; forwarding is only meaningful when direct'),
    (SETTINGS, 'peer networks and an independently secured proxy are explicitly configured.'),
    (MIDDLEWARE, 'does not authenticate a proxy, firewall the application, or make a proxy sanitize '
                 'incoming headers.'),
    (MIDDLEWARE, 'Do not set frame-ancestors here: development previews embed the'),
    (ADR_0184, 'These checks are not peer authentication.'),
    (ADR_0185, 'Setting the option back to zero stops new headers but does **not** send '
               '`max-age=0` or clear a previously cached HSTS policy.'),
    (TESTING, 'It does not verify actual TLS, browser caching or recovery'),
    (TESTING, 'It does not test or authenticate a real proxy chain'),
    (RUNBOOK, 'HSTS off, HTTPS redirection with no trusted proxy header, development hostnames in '
              '`ALLOWED_HOSTS`, health probes answering, the synthetic login limiter, '
              '`XFrameOptionsMiddleware` absent'),
    (ADR_0210, 'pin the complete header inventory'),
    (DESIGN, 'The shared stylesheet `static/css/site.css` is used by every current page'),
    (DESIGN, 'supplemental `static/css/staff.css`'),
]
# Every number this plan claims, as the flat string it must contain.
MEASURED = [
    '55 routes: 12 public and 43 staff',
    'Debug-import profile, 13 middleware entries',
    'Non-debug profile, 14 middleware entries',
    'share exactly six headers',
    'exactly eight headers',
    'ten header names',
    'nine common header names',
    '41 answers are 302',
    '0 of 3 HSTS features',
    'answered 301 with no HSTS header',
    '[true, null, 13]',
    '7 of 12',
    'Non-test `.py` occurrences of `Access-Control`: 0',
    '0 non-test modules',
    '200, 200, 200, then 429 with `Retry-After: 60`',
    '120 reads per keyed client in a 60-second window',
    '63 HTML templates',
    '25,166 bytes',
    '8,245 bytes',
    '217 lines with 0 occurrences of `tls`, `hsts` or `proxy`',
    '41/1/1 staff statuses',
    '13/14 middleware split',
]
DEPENDENT_SUITES = ('daroobank/test_no_read_audit.py', 'daroobank/test_hsts_configuration.py',
                    'daroobank/test_trusted_proxy_scheme.py',
                    'daroobank/test_content_security_policy.py',
                    'daroobank/test_staff_header_inventory.py',
                    'daroobank/test_public_route_privacy_matrix.py',
                    'catalog/test_public_read_privacy.py', 'daroobank/test_public_read_limit.py',
                    'daroobank/test_no_abuse_protection.py',
                    'daroobank/test_environment_documentation.py',
                    'daroobank/test_document_links.py', 'daroobank/test_mfa_implementation_plan.py',
                    'daroobank/test_secret_rotation_plan.py')
# The sixteen environment variables the application reads; no plan may add one.
ENV_READS = frozenset({
    'DAROOBANK_ALLOWED_HOSTS', 'DAROOBANK_DEBUG', 'DAROOBANK_HEALTH_PROBES_ENABLED',
    'DAROOBANK_HSTS_SECONDS', 'DAROOBANK_PUBLIC_READ_LIMIT', 'DAROOBANK_SECRET_KEY',
    'DAROOBANK_STAFF_LOGIN_THROTTLE', 'DAROOBANK_TRUSTED_PROXY_CIDRS',
    'DAROOBANK_TRUST_PROXY_SSL_HEADER', 'POSTGRES_CONN_MAX_AGE', 'POSTGRES_DB', 'POSTGRES_HOST',
    'POSTGRES_PASSWORD', 'POSTGRES_PORT', 'POSTGRES_SSLMODE', 'POSTGRES_USER',
})
ENV_LITERAL = re.compile(r"""(?:os\.environ(?:\.get|\[)|required_database_setting)\(\s*['"]"""
                         r"""((?:DAROOBANK|POSTGRES)_[A-Z0-9_]+)['"]""")
NEVER_HEADERS = ('x-frame-options', 'strict-transport-security',
                 'cross-origin-resource-policy', 'cross-origin-embedder-policy',
                 'permissions-policy')
BASE_PUBLIC = {'content-length', 'content-security-policy', 'content-type',
               'cross-origin-opener-policy', 'referrer-policy', 'x-content-type-options'}
READ_CLASS = BASE_PUBLIC | {'cache-control', 'x-robots-tag'}
SKIP_DIRS = frozenset({'.git', '.venv', '.cache', 'node_modules', '__pycache__'})


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


def subsections(text):
    return re.findall(r'^### (.*)$', text, re.M)


def section(text, heading):
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def tree_count(pattern, suffixes, non_test=False):
    regex = re.compile(pattern)
    total = 0
    for path in ROOT.rglob('*'):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if non_test and path.name.startswith('test_'):
            continue
        total += len(regex.findall(path.read_text(encoding='utf-8', errors='ignore')))
    return total


class PlanStructureTests(SimpleTestCase):
    def test_the_plan_states_its_own_shape(self):
        text = read(PLAN)
        self.assertTrue(text.startswith('# '), 'the plan does not open with a single top heading')
        self.assertEqual(sections(text), SECTIONS, 'the plan gained or lost a section')
        self.assertEqual(subsections(text), SUBSECTIONS, 'the measured subsections moved')
        decisions = flat(section(text, 'Candidate approach and decisions required'))
        found = re.findall(r'\d+\. \*\*(.+?)\*\*', decisions)
        self.assertEqual(found, DECISIONS, 'the decisions the plan leaves open changed')
        options = section(text, 'Options and what each costs')
        self.assertEqual(len(re.findall(r'^\| \*\*[A-G]\.', options, re.M)), len(OPTIONS),
                         'the option table changed size')
        for option in OPTIONS:
            with self.subTest(option=option):
                self.assertIn(f'**{option}**', options)
        required = section(text, 'Required behavior before any production exposure')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', required, re.M)), 7,
                         'the required-behavior list changed size')
        verification = section(text, 'Verification before any enablement')
        self.assertGreaterEqual(len(re.findall(r'^- ', verification, re.M)), 6,
                                'the verification list shrank below six items')

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        flat_plan = flat(read(PLAN))
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan,
                              'the plan stopped saying that it proposes and implements nothing')
        for phrase in ('no owner', 'not a TLS deployment', 'not an approval',
                       'counted from the pins and files above, not prototyped'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan)
        for phrase in FORBIDDEN_SELECTION:
            with self.subTest(forbidden=phrase):
                self.assertNotIn(phrase, flat_plan,
                                 'the plan selected an approach instead of pricing it')

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        flat_plan = flat(read(PLAN))
        for path, quote in QUOTED_REQUIREMENTS:
            with self.subTest(document=path.name, quote=quote[:40]):
                self.assertIn(quote, flat(read(path)),
                              'a document stopped saying what it is quoted for')
                self.assertIn(quote, flat_plan,
                              'the plan stopped quoting the requirement it answers')

    def test_the_plan_states_the_measured_numbers(self):
        flat_plan = flat(read(PLAN))
        for measurement in MEASURED:
            with self.subTest(measurement=measurement[:50]):
                self.assertIn(measurement, flat_plan,
                              f'the plan dropped the {measurement[:30]} it measured')

    def test_the_plan_names_the_documents_records_and_suites_it_depends_on(self):
        text = read(PLAN)
        for document in (DEPLOYMENT, RUNBOOK, SECURITY, EVIDENCE, TESTING, DESIGN):
            with self.subTest(document=document.name):
                self.assertIn(f'`docs/{document.name}`', text,
                              f'the plan stopped naming docs/{document.name}')
        for record in (ADR_0121, ADR_0184, ADR_0185, ADR_0210, ADR_0228, ADR):
            with self.subTest(record=record.name):
                self.assertTrue(record.is_file(), f'{record.name} does not exist')
                self.assertIn(f'ARCHITECTURE_DECISIONS/{record.name}', text,
                              'the plan stopped linking a record it is written against')
        for suite in DEPENDENT_SUITES + ('daroobank/test_network_tls_plan.py',):
            with self.subTest(suite=suite):
                self.assertIn(f'`{suite}`', text,
                              f'the plan stopped naming {suite}')


class MeasuredTreeTests(SimpleTestCase):
    def test_the_static_counts_are_the_measured_ones(self):
        templates = list((ROOT / 'templates').rglob('*.html'))
        self.assertEqual(len(templates), 63, 'the template count moved')
        self.assertEqual(len(list((ROOT / 'templates').glob('*.html'))), 9)
        self.assertEqual(len(list((ROOT / 'templates' / 'staff').rglob('*.html'))), 53)
        self.assertEqual(len(list((ROOT / 'templates' / 'partials').glob('*.html'))), 1)
        self.assertEqual((ROOT / 'static' / 'css' / 'site.css').stat().st_size, 25166,
                         'site.css byte count moved')
        self.assertEqual((ROOT / 'static' / 'css' / 'staff.css').stat().st_size, 8245,
                         'staff.css byte count moved')
        workflow = read(WORKFLOW)
        self.assertEqual(len(workflow.splitlines()), 217, 'the workflow line count moved')
        self.assertEqual(len(re.findall(r'tls|hsts|proxy', workflow, re.I)), 0,
                         'the workflow now mentions TLS, HSTS or a proxy')
        self.assertEqual(len(re.findall(r'https|header', workflow, re.I)), 0,
                         'the workflow now mentions https or a header')
        self.assertEqual(tree_count(r'Access-Control', {'.py'}, non_test=True), 0,
                         'a non-test module now mentions Access-Control')
        self.assertEqual(tree_count(r'HTTP_X_FORWARDED_FOR', {'.py'}, non_test=True), 0,
                         'a non-test module now reads X-Forwarded-For')
        design = read(DESIGN)
        self.assertIn('The shared stylesheet `static/css/site.css` is used by every current page',
                      flat(design))
        self.assertIn('supplemental `static/css/staff.css`', design)
        patterns = get_resolver().url_patterns
        self.assertEqual(len(patterns), 55, 'the route count moved')
        staff = [p for p in patterns if str(p.pattern).startswith('staff')]
        self.assertEqual(len(staff), 43, 'the staff route count moved')
        self.assertEqual(len(patterns) - len(staff), 12, 'the public route count moved')

    def test_the_settings_shape_is_the_measured_one(self):
        self.assertEqual(len(settings.MIDDLEWARE), 13,
                         'the debug-import middleware count moved off the pinned 13')
        for entry in settings.MIDDLEWARE:
            self.assertNotIn('cors', entry.lower(), 'a CORS middleware is installed')
        cors_modules = []
        for path in ROOT.rglob('*.py'):
            if any(part in SKIP_DIRS for part in path.parts) or path.name.startswith('test_'):
                continue
            try:
                tree = ast.parse(path.read_text(encoding='utf-8'))
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if (isinstance(node, ast.ClassDef)
                        and (node.name in ('Cors', 'CORS') or node.name.startswith('Cors'))):
                    cors_modules.append(f'{path.name}:{node.name}')
        self.assertEqual(cors_modules, [],
                         'a CORS class now exists outside tests: %s' % cors_modules)
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 0, 'HSTS is no longer off by default')
        self.assertFalse(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertFalse(settings.SECURE_HSTS_PRELOAD)
        self.assertIsNone(settings.SECURE_PROXY_SSL_HEADER, 'proxy-scheme trust is no longer off')
        self.assertEqual(settings.TRUSTED_PROXY_SCHEME_NETWORKS, ())
        self.assertEqual(settings.SECURE_REFERRER_POLICY, 'same-origin')
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertFalse(settings.SESSION_COOKIE_SECURE,
                         'secure cookies are a non-debug fact, not a debug-import one')
        self.assertFalse(settings.CSRF_COOKIE_SECURE)
        self.assertFalse(getattr(settings, 'SECURE_SSL_REDIRECT', False),
                         'the HTTPS redirect is a non-debug fact')
        self.assertFalse(settings.PUBLIC_READ_LIMIT_ENABLED,
                         'the public read limiter must stay off by default')
        self.assertTrue(settings.STAFF_PORTAL_ENABLED,
                        'the debug-import profile measured the portal open')
        self.assertFalse(settings.HEALTH_PROBES_ENABLED)
        source = read(SETTINGS)
        self.assertNotIn('SECURE_CROSS_ORIGIN_OPENER_POLICY', source,
                         'COOP is Django\'s default here, not a repository setting')
        self.assertEqual(read_limit.READ_LIMIT, 120)
        self.assertEqual(read_limit.WINDOW.total_seconds(), 60)
        self.assertEqual(read_limit.SCOPE, 'staff_security.public_read.v1')

    def test_database_free_public_responses_carry_the_profiled_headers(self):
        client = Client()
        plain = ('home', 'about', 'robots', 'sitemap')
        for name in plain:
            with self.subTest(route=name):
                response = client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(set(k.lower() for k in response.headers), BASE_PUBLIC,
                                 f'{name} no longer matches the six-header class')
                self.assertEqual(response['Referrer-Policy'], 'same-origin')
                self.assertNotIn('Cache-Control', response.headers)
                self.assertNotIn('X-Robots-Tag', response.headers)
        prices = client.get(reverse('prices'))
        self.assertEqual(set(k.lower() for k in prices.headers), BASE_PUBLIC | {'x-robots-tag'})
        self.assertEqual(prices['X-Robots-Tag'], 'noindex, follow')
        self.assertEqual(prices['Referrer-Policy'], 'same-origin')
        openapi = client.get(reverse('openapi_document'))
        self.assertEqual(set(k.lower() for k in openapi.headers), READ_CLASS)
        self.assertEqual(openapi['Referrer-Policy'], 'no-referrer')
        self.assertEqual(openapi['Cache-Control'], 'no-store')
        self.assertEqual(openapi['X-Robots-Tag'], 'noindex, follow')
        for name in ('health_live', 'health_ready'):
            with self.subTest(route=name):
                response = client.get(reverse(name))
                self.assertEqual(response.status_code, 404)
                self.assertEqual(set(k.lower() for k in response.headers), READ_CLASS)
                self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                self.assertEqual(response['Cache-Control'], 'no-store')
        login = client.get(reverse('staff_login'))
        self.assertEqual(login.status_code, 200)
        self.assertEqual(set(k.lower() for k in login.headers),
                         READ_CLASS | {'pragma', 'vary', 'expires'},
                         'the staff login page no longer matches its profiled class')
        self.assertEqual(login['Referrer-Policy'], 'same-origin')
        self.assertEqual(login['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(client.get(reverse('staff_logout')).status_code, 405)
        for response in (client.get(reverse(name)) for name in plain):
            for header in NEVER_HEADERS:
                self.assertNotIn(header, {k.lower() for k in response.headers},
                                 f'{header} appeared on a public response')
            self.assertFalse(any(k.lower().startswith('access-control')
                                 for k in response.headers),
                             'an Access-Control header appeared on a public response')


class NothingImplementedTests(SimpleTestCase):
    def test_no_new_header_middleware_environment_or_dependency_exists(self):
        found = set(ENV_LITERAL.findall(read(SETTINGS)))
        self.assertEqual(found, ENV_READS,
                         'settings.py now reads an environment variable this plan did not price')
        self.assertEqual(len(settings.MIDDLEWARE), 13, 'a middleware entry was added')
        self.assertIn('Django==5.2.19', read(REQUIREMENTS_IN))
        self.assertIn('psycopg[binary]==3.3.9', read(REQUIREMENTS_IN))
        self.assertNotIn('cors', read(REQUIREMENTS).lower(), 'a CORS dependency was added')
        self.assertEqual(tree_count(r'Permissions-Policy|Cross-Origin-Resource-'
                                    r'Policy|Cross-Origin-Embedder-Policy', {'.py'},
                                    non_test=True), 0,
                         'a policy header this plan measured as absent is now emitted')
        probes = [path.name for path in (ROOT / 'daroobank').glob('test_zz*')]
        self.assertEqual(probes, [], 'a temporary probe file is still in the tree')

    def test_the_limiter_proxy_and_hsts_defaults_remain_off(self):
        self.assertFalse(settings.PUBLIC_READ_LIMIT_ENABLED)
        self.assertEqual(read_limit.READ_LIMIT, 120)
        self.assertIsNone(settings.SECURE_PROXY_SSL_HEADER)
        self.assertEqual(settings.TRUSTED_PROXY_SCHEME_NETWORKS, ())
        self.assertEqual(settings.SECURE_HSTS_SECONDS, 0)
        self.assertFalse(settings.SECURE_HSTS_INCLUDE_SUBDOMAINS)
        self.assertFalse(settings.SECURE_HSTS_PRELOAD)


class NeighborDocumentTests(SimpleTestCase):
    def test_the_neighbour_documents_and_the_evidence_row_link_the_plan(self):
        for document in (DEPLOYMENT, RUNBOOK, SECURITY, TESTING, DESIGN, CHANGELOG):
            with self.subTest(document=document.name):
                text = read(document)
                self.assertIn('NETWORK_TLS_PLAN.md', text,
                              f'{document.name} does not name the plan')
                self.assertIn('0234-network-tls-plan.md', text,
                              f'{document.name} does not link the record')
        self.assertTrue(list(ROOT.joinpath('docs', 'ARCHITECTURE_DECISIONS')
                             .glob('0234-network-tls-plan.md')), 'the record is missing')
        self.assertIn('0234-network-tls-plan.md', read(ADR_INDEX),
                      'the record is not listed in the index')
        changelog = read(CHANGELOG)
        self.assertIn('## 2026-11-27 — ', changelog, 'the changelog entry is missing')
        evidence = read(EVIDENCE)
        row = next(line for line in evidence.splitlines()
                   if line.startswith('| Network and TLS |'))
        self.assertIn('NETWORK_TLS_PLAN.md', row, 'the evidence row does not name the plan')
        self.assertIn('0234-network-tls-plan.md', row, 'the evidence row does not link the record')
        for quote in ('Optional proxy-scheme trust and HSTS settings exist; both are off by default.',
                      'actual network isolation, trusted proxy configuration and header '
                      'sanitization, approved hostnames, TLS issuance/renewal, HTTPS/CSRF/cookie '
                      'checks and HSTS rollback plan; see ADRs 0184–0185.'):
            with self.subTest(quote=quote[:40]):
                self.assertIn(quote, flat(row),
                              'the evidence row dropped a gate sentence other suites pin')
