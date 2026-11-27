"""The API and permissions plan, and what this boundary enforces on the live runtime.

`docs/API_PERMISSIONS_PLAN.md` exists because five documents ask for route authorization,
scoped API authentication, author/reviewer separation and OpenAPI accuracy, while the parity
suites measure consistency against declared requirements inside `STAFF_PORTAL_ENABLED = DEBUG`.
This suite pins the plan to the code and to live PostgreSQL 16.2 measurements:

* 55 named routes (43 `staff_*` under `STAFF_PORTAL_ENABLED = DEBUG`, 12 non-staff including
  3 `/api/v1/*` and 2 `health_*`), with 36 `all of`, 4 `any of` and 1 `is_staff`-only route
  plus 2 authentication endpoints using 16 of 63 `auth_permission` rows;
* `StaffLoginView` accepting `PUT` (HTTP 200, unauthenticated) and overriding
  `settings.LOGIN_REDIRECT_URL` (`'staff_prices'`) to `/staff/` (`staff_workspace`);
* `docs/openapi.json` (3 paths, 5 responses, 3 schemas, 0 headers, 0 `securitySchemes`)
  against `docs/API_DESIGN.md`'s 11 unbuilt endpoints and live HTTP behavior (`8` 200 headers,
  HTML 405/403/429 responses, 120-char `q` slicing before control-char validation, and
  JSON vs HTML 404 split at `4,300` vs `4,301` digits in `/api/v1/products/{id}/`);
* active staff superusers bypassing all 41 matrix routes with 0 explicit grants, single
  accounts holding all 16 matrix permissions, 0 of 37 PostgreSQL `CHECK` constraints
  referencing actor/reviewer separation, and cross-revision self-review succeeding in both
  `clinical/services.py` and `catalog/identity.py` plus CLI `staged_by_id=None`;
* 15 of 16 `recheck_actor` sites calling `lock=False`, `sources.review_claim` committing after
  reviewer deactivation and password change, dormant sessions surviving an off/on toggle and
  evading `list_staff_sessions`/`revoke_staff_sessions` beyond 5,000 rows, 6 of 12 management
  commands running under `DEBUG=False`, and `settings.LOGGING == {}`.

All checks are synthetic measurements; nothing here approves endpoints or replaces an owner's
decision in `docs/AUTHORIZATION_REVIEW.md`.
"""
import ast
import json
import os
import re
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path
from threading import Event
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import CommandError, call_command, get_commands
from django.db import OperationalError, close_old_connections, connection
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone as dj_timezone

from catalog.identity import (create_formulation, create_ingredient, create_package, create_product,
                              digest as identity_digest, package_snapshot, review_package,
                              revise_package)
from catalog.intake import stage_products
from catalog.models import ProductCandidate, ProductPresentation
from catalog.services import MAX_QUERY_LENGTH
from clinical.evidence import evidence_state
from clinical.services import create_draft, review_draft
from daroobank import authorization_review
from daroobank.session_guard import authorization_fingerprint
from daroobank.test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS
from ingestion.models import ImportReceipt, ImportReceiptItem
from pricing.importer import stage_csv as stage_price_csv
from pricing.models import PriceCandidate
from sources.models import SourceClaim, SourceClaimReview
from sources.services import _lock_latest_review, record_claim, review_claim

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'API_PERMISSIONS_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0235-api-permissions-plan.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
OPENAPI = ROOT / 'docs' / 'openapi.json'
API_DESIGN = ROOT / 'docs' / 'API_DESIGN.md'
AUTHORIZATION_REVIEW = ROOT / 'docs' / 'AUTHORIZATION_REVIEW.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
OPERATIONS_RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
DEVELOPMENT_GUIDE = ROOT / 'docs' / 'DEVELOPMENT_GUIDE.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
REQUIREMENTS = ROOT / 'requirements.txt'
REQUIREMENTS_IN = ROOT / 'requirements.in'

SKIP_PARTS = frozenset({'.venv', '.cache', '.git', 'node_modules', '__pycache__', 'migrations',
                        'staticfiles'})
PROJECT_APPS = ('catalog', 'clinical', 'ingestion', 'pricing', 'sources', 'staff_security')
SECTIONS = [
    'What is true today, measured',
    'Candidate approach and decisions required',
    'Options and what each costs',
    'Required behavior before any enablement',
    'Verification before any enablement',
]
SUBSECTIONS = [
    'The URL surface and declared staff permissions',
    'Public API contract versus live behavior',
    'Superuser bypass, single-user accumulation and separation-of-duties boundaries',
    'In-flight locking, dormant sessions, management CLI and audit boundaries',
]
DECISIONS = [
    'Which public, institutional and internal endpoints belong in Phase 1, and what replaces `STAFF_PORTAL_ENABLED = DEBUG`?',
    'Is the current per-route requirement set approved, including `is_staff`-only on `staff_workspace` and `any of` on import and window inspection routes?',
    'Should an active superuser keep automatic access to all 41 staff routes, or must clinical, source and catalog review deny superusers without explicit scoped grants?',
    'May one account accumulate author and reviewer permissions across or within domains, or must mutually exclusive roles be enforced at grant time and in the database?',
    'Should separation of duties extend across revision lineages and into PostgreSQL constraints, or stay bound to immediate drafts and graphs?',
    'How are `docs/openapi.json`, Django error handlers (`400`, `403`, `404`, `405`, `429`) and query bounds reconciled before external clients rely on them?',
    'Which authentication scheme, scoping and revocation boundary applies to institutional and mobile API clients?',
    'How are dormant sessions beyond the 5,000-row scan bound, unlocked in-flight rechecks and unauthenticated management CLI commands closed and audited?',
]
OPTIONS = [
    'A. Leave the API and permission boundary as documented',
    'B. Close the OpenAPI and HTTP API contract drift on the 3 existing endpoints',
    'C. Remove active superuser bypass, block single-user add+review accumulation, and harden `StaffLoginView` and `LOGIN_REDIRECT_URL`',
    'D. Enforce lineage-wide separation of duties, row-locked `recheck_actor`, and PostgreSQL `CHECK` or trigger constraints',
    'E. Add scoped API token authentication and endpoint authorization for the proposed institutional/v1 endpoints',
    'F. Decouple staff portal activation from `DEBUG` and remove the 5,000-session bound and CLI bypass',
    'G. Keep Phase 1 read-only anonymous `/api/v1` only and defer authenticated APIs and production staff portal',
]
PROPOSAL_PHRASES = [
    'This document is a **proposal**',
    'It has no owner and no approval',
    'must not be read as a decision',
    '**Nothing is implemented.**',
                      'OpenAPI edit or permission boundary change was implemented and reverted',
    'no cascade of pin failures was run',
]
QUOTED_REQUIREMENTS = [
    (EVIDENCE, 'Versioned OpenAPI and selected server-side authorization tests exist'),
    (EVIDENCE, "approve each route's requirement, approve exposure and permissions for the intended deployment, and add threat modeling and an independent security assessment"),
    (API_DESIGN, 'The rest of this document is a proposed contract, not running endpoints'),
    (API_DESIGN, 'scoped short-lived tokens with revocation and rate/usage limits'),
    (API_DESIGN, '405 and CSRF errors are not part of the API JSON error schema'),
    (API_DESIGN, 'Public rate limiting, production-scale indexing and snapshot-consistent export are not implemented'),
    (AUTHORIZATION_REVIEW, 'the inventory is derived and drift-checked; the judgement is unsigned'),
    (SECURITY, 'Default deny; server-side object-level authorization and separation of author/reviewer. Users may hold multiple roles; implement auditable permission grants, revocation and periodic review'),
    (SECURITY, 'Super administrator | Manage roles/security configuration; no automatic clinical approval bypass'),
    (DEPLOYMENT, 'No deployment has been performed or authorized.'),
]
API_DESIGN_UNBUILT_PATHS = (
    '/drugs/{id}', '/drugs/{id}/monographs', '/products/{id}', '/packages/{id}',
    '/packages/{id}/prices', '/manufacturers/{id}', '/safety-alerts/{id}',
    '/admin/candidates/{id}/decisions', '/admin/content-versions/{id}/decisions',
    '/admin/crawl-runs', '/admin/crawl-runs/{id}',
)
UNEXPECTED_PACKAGES = ('djangorestframework', 'rest_framework', 'pyjwt', 'PyJWT', 'authlib',
                       'django-oauth-toolkit', 'oauthlib', 'drf-spectacular')
NON_DEBUG_COMMANDS_ALLOWED = frozenset({
    'check_deployment_readiness',
    'inspect_catalog_irc',
    'inspect_catalog_quality',
    'inspect_ingestion_window',
    'list_price_candidates',
    'stage_price_csv',
})
NON_DEBUG_COMMANDS_REFUSED = frozenset({
    'cleanup_staff_login_windows',
    'inspect_postgresql_access',
    'inspect_postgresql_schema',
    'list_staff_sessions',
    'repair_catalog_projection',
    'revoke_staff_sessions',
})


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    return ' '.join(text.split())


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


def subsections(text):
    return re.findall(r'^### (.*)$', text, re.M)


def section(text, heading):
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def python_modules():
    return sorted(path for path in ROOT.rglob('*.py')
                  if not (SKIP_PARTS & set(path.relative_to(ROOT).parts)))


def project_modules():
    return [path for path in python_modules()
            if not path.name.startswith('test_') and path.name != 'tests.py']


def command_modules():
    return [path for path in project_modules()
            if 'management/commands' in path.relative_to(ROOT).as_posix()
            and path.name != '__init__.py']


class PlanStructureTests(SimpleTestCase):
    def test_the_plan_states_its_own_shape(self):
        text = read(PLAN)
        self.assertEqual(sections(text), SECTIONS)
        self.assertEqual(subsections(text), SUBSECTIONS)
        decisions = section(text, 'Candidate approach and decisions required')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', decisions, re.M)), len(DECISIONS))
        for opener in DECISIONS:
            with self.subTest(decision=opener[:45]):
                self.assertIn(opener, flat(decisions))
        options = section(text, 'Options and what each costs')
        self.assertEqual(len(re.findall(r'^\| \*\*[A-G]\.', options, re.M)), len(OPTIONS))
        for option in OPTIONS:
            with self.subTest(option=option[:45]):
                self.assertIn(f'**{option}**', options)
        required = section(text, 'Required behavior before any enablement')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', required, re.M)), 7)
        verification = section(text, 'Verification before any enablement')
        self.assertEqual(len(re.findall(r'^- ', verification, re.M)), 6)

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        text = read(PLAN)
        flat_text = flat(text)
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text)
        for claim in ('Owner:', 'owned by', 'approved by', 'signed off by'):
            self.assertNotIn(claim, text)

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        flat_plan = flat(read(PLAN))
        for path, quote in QUOTED_REQUIREMENTS:
            with self.subTest(document=path.name, quote=quote[:40]):
                self.assertIn(quote, flat(read(path)))
                self.assertIn(quote, flat_plan)

    def test_the_plan_states_the_measured_counts_and_existing_targets(self):
        text = read(PLAN)
        flat_plan = flat(text)
        for token in ('55 named routes', '43 `staff_*` routes', '12 non-staff routes',
                      '36 staff routes require `all of`', '4 routes require `any of`',
                      '16 permissions', '63 rows', '47 permission rows',
                      '41/41', '37 `CHECK` constraints', '15 of 16 `recheck_actor` sites',
                      '5,000 rows', '6 of 12 management commands', '120', '4,300', '4,301',
                      '179', '25,938', '1,709', 'Retry-After: 60', 'LOGGING == {}'):
            with self.subTest(token=token):
                self.assertIn(token, flat_plan)
        for name in set(re.findall(r'`([\w./-]+\.py)`', text)):
            with self.subTest(module=name):
                self.assertTrue((ROOT / name).is_file(), f'missing module {name}')
        for name in set(re.findall(r'`([a-zA-Z0-9_][\w./-]+\.(?:json|md|yaml))`', text)):
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), f'missing file {name}')
        for number in set(re.findall(r'\b0\d{3}\b', text)):
            with self.subTest(adr=number):
                self.assertTrue(list(ADR_DIR.glob(f'{number}-*.md')), f'missing ADR {number}')


class UrlSurfaceAndPermissionBoundaryTests(SimpleTestCase):
    def test_resolver_and_permission_matrix_match_the_measured_counts(self):
        names = authorization_review.route_names()
        staff_names = {name for name in names if name.startswith('staff_')}
        public_names = {name for name in names if not name.startswith('staff_')}
        self.assertEqual(len(names), 55)
        self.assertEqual(len(staff_names), 43)
        self.assertEqual(len(public_names), 12)
        self.assertEqual(len(ROUTES), 41)
        self.assertEqual(len(ALL_PERMISSIONS), 16)
        self.assertEqual(len(VIEW_PERMISSIONS), 6)
        counts = {'all': 0, 'any': 0, 'staff': 0}
        for _name, _kwargs, _method, req in ROUTES:
            counts[req[0]] += 1
        self.assertEqual(counts, {'all': 36, 'any': 4, 'staff': 1})
        self.assertEqual([row['name'] for row in authorization_review.public_rows()
                          if row['pattern'].startswith('api/v1/')],
                         ['search_api', 'openapi_document', 'presentation_api'])

    def test_openapi_specification_omits_headers_error_codes_and_method_or_limit_responses(self):
        spec = json.loads(read(OPENAPI))
        self.assertEqual(spec['openapi'], '3.0.3')
        self.assertEqual(spec['info']['version'], '1.0.0')
        self.assertEqual(sorted(spec['paths']),
                         ['/api/v1/openapi.json', '/api/v1/products/{id}/', '/api/v1/search/'])
        self.assertEqual(sorted(spec['components']['schemas']), ['Error', 'Presentation', 'SearchPage'])
        self.assertNotIn('securitySchemes', spec['components'])
        self.assertNotIn('security', spec)
        statuses = set()
        headers = 0
        for path_item in spec['paths'].values():
            for op in path_item.values():
                for code, resp in op['responses'].items():
                    statuses.add(code)
                    headers += len(resp.get('headers', {}))
        self.assertEqual(sorted(statuses), ['200', '400', '404'])
        self.assertEqual(headers, 0)
        q_param = next(p for p in spec['paths']['/api/v1/search/']['get']['parameters'] if p['name'] == 'q')
        self.assertEqual(q_param['schema'], {'type': 'string'})
        id_param = next(p for p in spec['paths']['/api/v1/products/{id}/']['get']['parameters'] if p['name'] == 'id')
        self.assertNotIn('maximum', id_param['schema'])
        self.assertEqual(spec['components']['schemas']['Error']['properties']['error']['properties']['code'],
                         {'type': 'string'})
        api_design = read(API_DESIGN)
        for path in API_DESIGN_UNBUILT_PATHS:
            with self.subTest(path=path):
                self.assertIn(path, api_design)

    def test_recheck_sites_logging_and_management_command_gates(self):
        recheck_sites = []
        logging_imports = []
        for path in project_modules():
            rel = path.relative_to(ROOT).as_posix()
            tree = ast.parse(read(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    if any(alias.name == 'logging' or alias.name.startswith('logging.') for alias in node.names):
                        logging_imports.append(rel)
                elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('logging'):
                    logging_imports.append(rel)
                elif isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'recheck_actor':
                    lock_val = any(kw.arg == 'lock' and isinstance(kw.value, ast.Constant) and kw.value.value is True
                                   for kw in node.keywords)
                    recheck_sites.append((rel, node.lineno, lock_val))
        self.assertEqual(len(recheck_sites), 16)
        self.assertEqual(sum(1 for _f, _l, lock in recheck_sites if lock), 1)
        self.assertEqual([(f, l) for f, l, lock in recheck_sites if lock], [('sources/services.py', 113)])
        self.assertEqual(logging_imports, [])
        self.assertEqual(settings.LOGGING, {})

        project_cmds = {name for name, app in get_commands().items()
                        if app in (*PROJECT_APPS, 'daroobank')}
        self.assertEqual(len(project_cmds), 12)
        self.assertEqual(project_cmds, NON_DEBUG_COMMANDS_ALLOWED | NON_DEBUG_COMMANDS_REFUSED)
        debug_checks = {}
        for path in command_modules():
            src = read(path)
            debug_checks[path.stem] = 'settings.DEBUG' in src
        self.assertEqual({k for k, v in debug_checks.items() if not v},
                         NON_DEBUG_COMMANDS_ALLOWED - {'check_deployment_readiness'})
        self.assertEqual(settings.LOGIN_REDIRECT_URL, 'staff_prices')
        self.assertIn('STAFF_PORTAL_ENABLED = DEBUG', read(SETTINGS))


class NothingImplementedTests(SimpleTestCase):
    def test_no_api_token_role_sod_or_audit_control_exists_while_the_plan_says_so(self):
        flat_plan = flat(read(PLAN))
        for phrase in ('**Nothing is implemented.**', '**0** `securitySchemes`', '0 of 37'):
            self.assertIn(phrase, flat_plan)
        req_in = read(REQUIREMENTS_IN)
        req_txt = read(REQUIREMENTS)
        self.assertEqual(len([line for line in req_in.splitlines() if line.strip()]), 4)
        self.assertEqual(len(req_txt.splitlines()), 94)
        for pkg in UNEXPECTED_PACKAGES:
            self.assertNotIn(pkg, req_in)
            self.assertNotIn(pkg, req_txt)
        models = [m for m in apps.get_models() if m._meta.app_label in PROJECT_APPS]
        self.assertEqual(len(models), 24)
        self.assertEqual([m.__name__ for m in models
                          if re.search(r'(?i)(ApiToken|ApiKey|RoleAssignment|PermissionAudit)', m.__name__)], [])
        self.assertEqual(len(list(ROOT.glob('*/migrations/0*.py'))), 17)
        self.assertNotIn('AUTHENTICATION_BACKENDS', read(SETTINGS))
        self.assertEqual(settings.SECRET_KEY_FALLBACKS, [])


class PlanConsequenceTests(SimpleTestCase):
    def test_the_neighbouring_documents_name_the_plan_and_what_it_measured(self):
        for path, phrases in (
            (API_DESIGN, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (AUTHORIZATION_REVIEW, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (SECURITY, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (DEPLOYMENT, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (OPERATIONS_RUNBOOK, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (DEVELOPMENT_GUIDE, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (TESTING, ['test_api_permissions_plan.py', 'API_PERMISSIONS_PLAN.md']),
            (EVIDENCE, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
            (CHANGELOG, ['API_PERMISSIONS_PLAN.md', '0235-api-permissions-plan.md']),
        ):
            text = read(path)
            for phrase in phrases:
                with self.subTest(document=path.name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_the_record_states_its_decision_and_its_limits(self):
        text = read(ADR)
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith('# 0235 — '))
        self.assertIn('Date: 2026-11-27', text)
        self.assertIn('Status: accepted', text)
        self.assertRegex(text, re.compile(r'^Suite: `daroobank/test_api_permissions_plan\.py`', re.M))
        self.assertEqual(sections(text), ['Context', 'Decision', 'Measured behavior', 'Red checks',
                                          'Consequences', 'Limitations'])
        decisions = section(text, 'Decision')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', decisions, re.M)), 4)
        self.assertIn('**Nothing was implemented.**', decisions)
        limitations = section(text, 'Limitations')
        self.assertEqual(len(re.findall(r'^- ', limitations, re.M)), 6)
        red = section(text, 'Red checks')
        red_rows = [line for line in red.splitlines() if re.match(r'^\| \d+ \|', line)]
        self.assertEqual(len(red_rows), 20)
        self.assertIn('Caught by', red)
        index = read(ADR_INDEX)
        bullets = [line for line in index.splitlines() if '0235-api-permissions-plan.md' in line]
        self.assertEqual(len(bullets), 1)
        self.assertIn('../API_PERMISSIONS_PLAN.md', text)


@override_settings(STAFF_PORTAL_ENABLED=True)
class LiveApiAndPermissionsMeasurementTests(TransactionTestCase):
    def _create_published_presentation(self):
        return ProductPresentation.objects.create(
            name_fa='داروی تست الف',
            name_en='a' * 120,
            manufacturer='سازنده تست',
            strength='50 mg',
            dosage_form='قرص',
            package_description='10 عدد',
            irc='123456',
            source_name='منبع رسمی تست',
            source_url='https://example.org/pub',
            published=True,
            verified_at=dj_timezone.now(),
            irc_normalized='123456',
        )

    def test_public_api_contract_drift_and_rate_limit_behavior(self):
        self._create_published_presentation()
        client = Client()

        # 1. MAX_QUERY_LENGTH=120 slicing precedes Unicode control filtering.
        r_trunc = client.get('/api/v1/search/', {'q': ('a' * MAX_QUERY_LENGTH) + 'ZZZZ_IGNORED'})
        self.assertEqual(r_trunc.status_code, 200)
        self.assertEqual(len(r_trunc.json()['data']), 1)

        r_ctrl_inside = client.get('/api/v1/search/', {'q': ('a' * 10) + '\x00'})
        self.assertEqual(r_ctrl_inside.status_code, 400)
        self.assertEqual(r_ctrl_inside.json()['error']['code'], 'invalid_query')

        r_ctrl_past = client.get('/api/v1/search/', {'q': ('a' * MAX_QUERY_LENGTH) + '\x00'})
        self.assertEqual(r_ctrl_past.status_code, 200)

        # 2. Integer-digit boundary splits /api/v1/products/{id}/ 404 between JSON and HTML.
        self.assertEqual(sys.get_int_max_str_digits(), 4300)
        for raw_id in ('0', str(2 ** 63), '9' * 4300):
            resp = client.get(f'/api/v1/products/{raw_id}/')
            self.assertEqual(resp.status_code, 404)
            self.assertEqual(resp.headers['Content-Type'], 'application/json')
            self.assertEqual(resp.json()['error']['code'], 'not_found')

        with self.assertLogs('django.request', level='WARNING'):
            with override_settings(DEBUG=False):
                r_4301_false = client.get(f"/api/v1/products/{'9' * 4301}/")
                self.assertEqual(r_4301_false.status_code, 404)
                self.assertEqual(r_4301_false.headers['Content-Type'], 'text/html; charset=utf-8')
                self.assertEqual(len(r_4301_false.content), 179)

            with override_settings(DEBUG=True):
                r_4301_true = client.get(f"/api/v1/products/{'9' * 4301}/")
                self.assertEqual(r_4301_true.status_code, 404)
                self.assertEqual(r_4301_true.headers['Content-Type'], 'text/html; charset=utf-8')
                self.assertEqual(len(r_4301_true.content), 25938)
                self.assertIn(b'daroobank.urls', r_4301_true.content)

        # 3. 200 headers, HTML 405, HTML 403 CSRF, and HTML 429 are all outside openapi.json.
        r_spec = client.get('/api/v1/openapi.json')
        self.assertEqual(r_spec.status_code, 200)
        self.assertEqual(sorted(r_spec.headers.keys()), [
            'Cache-Control', 'Content-Length', 'Content-Security-Policy', 'Content-Type',
            'Cross-Origin-Opener-Policy', 'Referrer-Policy', 'X-Content-Type-Options', 'X-Robots-Tag',
        ])

        csrf_client = Client(enforce_csrf_checks=True)
        for path in ('/api/v1/search/', '/api/v1/products/1/', '/api/v1/openapi.json'):
            for method in ('post', 'put', 'patch', 'delete', 'options'):
                resp = getattr(client, method)(path)
                self.assertEqual(resp.status_code, 405)
                self.assertEqual(resp.headers['Content-Type'], 'text/html; charset=utf-8')
                self.assertEqual(resp.headers['Allow'], 'GET, HEAD')
                self.assertEqual(len(resp.content), 0)
            for method in ('post', 'put', 'patch', 'delete'):
                resp = getattr(csrf_client, method)(path)
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(resp.headers['Content-Type'], 'text/html; charset=utf-8')
                self.assertEqual(len(resp.content), 1709)

        with override_settings(PUBLIC_READ_LIMIT_ENABLED=True):
            for _ in range(120):
                self.assertEqual(client.get('/api/v1/search/', {'q': 'a'}).status_code, 200)
            r_429 = client.get('/api/v1/search/', {'q': 'a'})
            self.assertEqual(r_429.status_code, 429)
            self.assertEqual(r_429.headers['Content-Type'], 'text/html; charset=utf-8')
            self.assertEqual(r_429.headers['Retry-After'], '60')
            self.assertEqual(len(r_429.content), 0)

    def test_superuser_bypass_permission_accumulation_and_sod_boundaries(self):
        User = get_user_model()
        self.assertEqual(Permission.objects.count(), 63)

        # 0 of 37 PostgreSQL CHECK constraints reference user/actor/reviewer columns.
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT con.conname, pg_get_constraintdef(con.oid)
                FROM pg_constraint con
                JOIN pg_class c ON c.oid = con.conrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND con.contype = 'c'
            """)
            checks = cursor.fetchall()
        self.assertEqual(len(checks), 37)
        self.assertEqual([name for name, definition in checks
                          if any(tok in definition for tok in ('user', 'author', 'reviewer', 'recorded_by', 'staged_by'))],
                         [])

        super_staff = User.objects.create_user('api-plan-super', password='synthetic-password-1234',
                                               is_staff=True, is_superuser=True)
        super_nonstaff = User.objects.create_user('api-plan-super-ns', password='synthetic-password-1234',
                                                  is_staff=False, is_superuser=True)
        accumulated = User.objects.create_user('api-plan-accumulated', password='synthetic-password-1234',
                                               is_staff=True)
        all_perms = list(Permission.objects.filter(codename__in=[codename for _app, codename in ALL_PERMISSIONS]))
        accumulated.user_permissions.add(*all_perms)
        self.assertEqual(accumulated.user_permissions.count(), 16)

        # Active superuser with zero explicit grants reaches all 41 matrix routes; non-staff gets 403.
        self.assertEqual(super_staff.user_permissions.count(), 0)
        self.assertEqual(super_staff.groups.count(), 0)
        c_super = Client()
        c_super.force_login(super_staff)
        c_nonstaff = Client()
        c_nonstaff.force_login(super_nonstaff)
        for name, kwargs, method, _req in ROUTES:
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            r_ok = c_super.get(url) if method == 'GET' else c_super.post(url, {})
            self.assertNotEqual(r_ok.status_code, 403, f'superuser denied on {name}')
            r_no = c_nonstaff.get(url) if method == 'GET' else c_nonstaff.post(url, {})
            self.assertEqual(r_no.status_code, 403, f'non-staff superuser allowed on {name}')

        # StaffLoginView PUT & LOGIN_REDIRECT_URL vs /staff/ redirect override.
        login_url = reverse('staff_login')
        self.assertEqual(c_nonstaff.get(login_url).status_code, 200)
        put_client = Client()
        r_put = put_client.put(login_url)
        self.assertEqual(r_put.status_code, 200)
        self.assertNotIn('_auth_user_id', put_client.session)

        login_client = Client()
        r_login = login_client.post(login_url, {'username': 'api-plan-super', 'password': 'synthetic-password-1234'})
        self.assertEqual(r_login.status_code, 302)
        self.assertEqual(r_login.headers['Location'], '/staff/')
        self.assertEqual(settings.LOGIN_REDIRECT_URL, 'staff_prices')

        # Create domain objects authored by super_staff and verify self-review refusal (403).
        claim, _ = record_claim(actor=super_staff, data={
            'source_name': 'منبع تست', 'source_url': 'https://example.org/src',
            'owner': 'ناشر', 'evidence_url': 'https://example.org/ev', 'evidence_note': '',
            'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
            'starts_on': None, 'expires_on': None,
        })
        p_csv = ('source_record_id,name_fa,name_en,manufacturer,strength,dosage_form,package_description,irc\n'
                 'p-sr-1,نام فارسی,TestEng,سازنده,10 mg,قرص,10 عدد,111\n').encode('utf-8')
        stage_products(BytesIO(p_csv), 'منبع', 'https://example.org/p1',
                       actor=super_staff, commit=True, rights_attested=True)
        prod = ProductCandidate.objects.get(source_record_id='p-sr-1')
        c_csv = ('source_record_id,irc,manufacturer,strength,dosage_form,package_description,amount,currency,category,unit,effective_date,source_published_date\n'
                 'sr-1,111,سازنده,10 mg,قرص,10 عدد,100000,RIAL,retail,package,2026-01-01,2026-01-01\n').encode('utf-8')
        stage_price_csv(BytesIO(c_csv), 'منبع', 'https://example.org/c1',
                        commit=True, rights_attested=True, staged_by=super_staff)
        price = PriceCandidate.objects.get(source_record_id='sr-1')
        draft_data = {
            'subject': 'موضوع علمی', 'audience': 'patient', 'title': 'عنوان علمی',
            'statement': 'متن علمی آزمایشی با طول کافی', 'reference_title': 'مرجع علمی',
            'reference_url': 'https://example.org/ref', 'reference_location': 'صفحه ۱',
            'reference_author': 'نویسنده', 'reference_version': '1',
            'reference_published_on': date(2026, 1, 1), 'reference_accessed_on': date(2026, 1, 2),
        }
        draft_v1 = create_draft(actor=super_staff, data=draft_data)
        ing = create_ingredient(actor=accumulated, data={
            'name_fa': 'ماده', 'name_en': 'Ing', 'source_name': 'منبع', 'source_url': 'https://example.org/i',
        })
        form = create_formulation(actor=accumulated, data={
            'name': 'فرمول', 'dosage_form': 'قرص', 'route': 'خوراکی',
            'source_name': 'منبع', 'source_url': 'https://example.org/f',
        }, components=[{
            'ingredient_id': ing.pk, 'numerator': Decimal('5.0000'), 'numerator_unit': 'mg',
            'denominator': Decimal('1.0000'), 'denominator_unit': 'tablet',
        }])
        iprod = create_product(actor=accumulated, data={
            'name': 'محصول', 'brand': 'برند', 'manufacturer': 'سازنده',
            'source_name': 'منبع', 'source_url': 'https://example.org/ip',
        }, formulation_id=form.pk)
        pkg_v1 = create_package(actor=super_staff, data={
            'description': '10 عدد', 'quantity': Decimal('10.0000'), 'quantity_unit': 'tablet',
            'irc': '222', 'source_name': 'منبع', 'source_url': 'https://example.org/pkg1',
        }, product_id=iprod.pk)

        ev_hash = evidence_state(draft_v1)['fingerprint']
        pkg1_hash = identity_digest(package_snapshot(pkg_v1))
        for url, payload in (
            (reverse('staff_source_review', args=[claim.pk]),
             {'decision': 'further_review', 'reason': 'دلیل آزمایشی کافی', 'expected_review': 0, 'expected_hash': claim.payload_sha256}),
            (reverse('staff_product_review', args=[prod.pk]),
             {'decision': 'reject', 'reason': 'دلیل آزمایشی کافی', 'expected_review': 0, 'expected_hash': prod.payload_sha256}),
            (reverse('staff_price_review', args=[price.pk]),
             {'decision': 'reject', 'reason': 'دلیل آزمایشی کافی', 'expected_review': 0, 'expected_product': 0, 'expected_product_hash': ''}),
            (reverse('staff_clinical_review', args=[draft_v1.pk]),
             {'decision': 'further_review', 'reason': 'دلیل آزمایشی کافی', 'expected_review': 0, 'expected_hash': draft_v1.payload_sha256, 'expected_evidence_hash': ev_hash}),
            (reverse('staff_identity_review', args=[pkg_v1.pk]),
             {'decision': 'reject', 'reason': 'دلیل آزمایشی کافی', 'expected_review': 0, 'expected_graph_hash': pkg1_hash}),
        ):
            self.assertEqual(c_super.post(url, payload).status_code, 403)

        # Revision SoD gaps: v1 author can review v2 revised by another account in both clinical & identity.
        draft_v2 = create_draft(
            actor=accumulated, data={**draft_data, 'statement': 'نسخه دوم با ویرایش همکار'},
            parent_id=draft_v1.pk, expected_parent_hash=draft_v1.payload_sha256,
            change_reason='اصلاح متنی نسخه دوم',
        )
        c_review = review_draft(
            actor=super_staff, draft_id=draft_v2.pk, decision='further_review',
            reason='نویسنده نسخه اول در حال بررسی نسخه دوم است.',
            expected_review=0, expected_hash=draft_v2.payload_sha256,
        )
        self.assertIsNotNone(c_review.pk)

        pkg_v2 = revise_package(
            actor=accumulated, parent_id=pkg_v1.pk,
            data={'description': '20 عدد', 'quantity': Decimal('20.0000'), 'quantity_unit': 'tablet',
                  'irc': '223', 'source_name': 'منبع', 'source_url': 'https://example.org/pkg2'},
            change_reason='اصلاح توضیح بسته‌بندی در نسخه دوم',
            expected_graph_hash=pkg1_hash, expected_review=0,
        )
        id_review = review_package(
            actor=super_staff, package_id=pkg_v2.pk, decision='reject',
            reason='ثبت‌کننده بسته قبلی در حال بازبینی نسخه اصلاح‌شده است.',
            expected_review=0, expected_graph_hash=identity_digest(package_snapshot(pkg_v2)),
        )
        self.assertIsNotNone(id_review.pk)

    def test_in_flight_race_dormant_sessions_scan_cap_and_nondebug_cli(self):
        User = get_user_model()
        writer = User.objects.create_user('api-plan-writer', password='synthetic-password-1234', is_staff=True)
        reviewer = User.objects.create_user('api-plan-reviewer', password='synthetic-password-1234', is_staff=True)
        perms = list(Permission.objects.filter(codename__in=[codename for _app, codename in ALL_PERMISSIONS]))
        writer.user_permissions.add(*perms)
        reviewer.user_permissions.add(*perms)

        # 1. Dormant session survival across off/on is_active toggle and 5,000-row scan cap.
        c = Client()
        c.force_login(writer)
        self.assertEqual(c.get(reverse('staff_workspace')).status_code, 200)
        fp_before = authorization_fingerprint(User.objects.get(pk=writer.pk))
        User.objects.filter(pk=writer.pk).update(is_active=False)
        self.assertIsNone(authorization_fingerprint(User.objects.get(pk=writer.pk)))
        self.assertEqual(c.get('/api/v1/openapi.json').status_code, 200)
        User.objects.filter(pk=writer.pk).update(is_active=True)
        self.assertEqual(authorization_fingerprint(User.objects.get(pk=writer.pk)), fp_before)
        self.assertEqual(c.get(reverse('staff_workspace')).status_code, 200)

        Session.objects.all().delete()
        target_key = 'z' * 32
        other_payload = SessionStore().encode({'_auth_user_id': str(reviewer.pk), '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend'})
        writer_payload = SessionStore().encode({'_auth_user_id': str(writer.pk), '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend'})
        exp = datetime(2030, 1, 1, tzinfo=timezone.utc)
        Session.objects.bulk_create(
            [Session(session_key=f'0000{idx:028d}', session_data=other_payload, expire_date=exp) for idx in range(5000)]
            + [Session(session_key=target_key, session_data=writer_payload, expire_date=exp)]
        )
        with override_settings(DEBUG=True):
            out_list = StringIO()
            call_command('list_staff_sessions', '--username', 'api-plan-writer', stdout=out_list)
            listed = json.loads(out_list.getvalue())
            self.assertEqual((listed['scanned'], listed['sessions_matched']), (5000, 0))
            out_rev = StringIO()
            call_command('revoke_staff_sessions', '--username', 'api-plan-writer', '--apply', stdout=out_rev)
            revoked = json.loads(out_rev.getvalue())
            self.assertEqual((revoked['scanned'], revoked['matched'], revoked['revoked']), (5000, 0, 0))
            self.assertTrue(Session.objects.filter(session_key=target_key).exists())

        # 2. Unlocked recheck_actor race vs lock=True blocking only auth_user update.
        claim, _ = record_claim(actor=writer, data={
            'source_name': 'منبع ریس', 'source_url': 'https://example.org/race',
            'owner': 'ناشر', 'evidence_url': 'https://example.org/race-ev', 'evidence_note': '',
            'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
            'starts_on': None, 'expires_on': None,
        })
        entered_lock, proceed = Event(), Event()

        def pause_after_recheck(claim_obj):
            entered_lock.set()
            if not proceed.wait(10):
                raise TimeoutError('Race did not resume')
            return _lock_latest_review(claim_obj)

        def concurrent_review():
            close_old_connections()
            try:
                return review_claim(
                    actor=User.objects.get(pk=reviewer.pk), claim_id=claim.pk,
                    decision='further_review', reason='بررسی همزمان پس از غیرفعال‌سازی',
                    expected_review=0, expected_hash=claim.payload_sha256,
                )
            finally:
                close_old_connections()

        with patch('sources.services._lock_latest_review', side_effect=pause_after_recheck):
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(concurrent_review)
                try:
                    self.assertTrue(entered_lock.wait(10))
                    r_fresh = User.objects.get(pk=reviewer.pk)
                    r_fresh.is_active = False
                    r_fresh.set_password('rotated-mid-flight-1234')
                    r_fresh.save(update_fields=['is_active', 'password'])
                finally:
                    proceed.set()
                committed_review = fut.result(timeout=15)
        self.assertIsNotNone(committed_review.pk)
        self.assertFalse(User.objects.get(pk=reviewer.pk).is_active)

        lock_ready, lock_resume = Event(), Event()
        from sources.services import _find_or_create_claim

        def pause_locked(*args, **kwargs):
            lock_ready.set()
            if not lock_resume.wait(10):
                raise TimeoutError('Locked writer did not resume')
            return _find_or_create_claim(*args, **kwargs)

        def locked_writer():
            close_old_connections()
            try:
                return record_claim(actor=User.objects.get(pk=writer.pk), data={
                    'source_name': 'منبع قفل', 'source_url': 'https://example.org/locked',
                    'owner': 'ناشر', 'evidence_url': 'https://example.org/locked-ev', 'evidence_note': '',
                    'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
                    'starts_on': None, 'expires_on': None,
                })
            finally:
                close_old_connections()

        with patch('sources.services._find_or_create_claim', side_effect=pause_locked):
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(locked_writer)
                try:
                    self.assertTrue(lock_ready.wait(10))
                    with connection.cursor() as cur:
                        cur.execute("SET lock_timeout = '200ms'")
                        with self.assertRaises(OperationalError) as ctx:
                            User.objects.filter(pk=writer.pk).update(is_active=False)
                        self.assertEqual(getattr(ctx.exception.__cause__, 'sqlstate', None), '55P03')
                        cur.execute('SET lock_timeout = 0')
                    # M2M permission removal does not block on the auth_user row lock.
                    writer.user_permissions.clear()
                finally:
                    lock_resume.set()
                _, created_locked = fut.result(timeout=15)
        self.assertTrue(created_locked)

        # 3. Non-debug CLI execution vs debug-only commands.
        with override_settings(DEBUG=False):
            for cmd in sorted(NON_DEBUG_COMMANDS_REFUSED):
                with self.subTest(refused_cmd=cmd):
                    with self.assertRaises(CommandError):
                        call_command(cmd, stdout=StringIO(), stderr=StringIO())

            with tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False, encoding='utf-8') as f:
                f.write('amount,currency,category,unit,effective_date,irc,manufacturer,strength,dosage_form,package_description,source_record_id,source_published_date\n'
                        '250000,RIAL,retail,package,2026-01-01,777,سازنده تست,5 mg,قرص,10 عدد,cli-1,2026-01-01\n')
                csv_path = f.name
            try:
                before_receipts = ImportReceipt.objects.count()
                before_items = ImportReceiptItem.objects.count()
                call_command('stage_price_csv', csv_path, '--source-name', 'منبع CLI',
                             '--source-url', 'https://example.org/cli', '--commit',
                             '--attest-authorized', stdout=StringIO())
                cand = PriceCandidate.objects.get(source_record_id='cli-1')
                self.assertIsNone(cand.staged_by_id)
                self.assertEqual(ImportReceipt.objects.count(), before_receipts)
                self.assertEqual(ImportReceiptItem.objects.count(), before_items)
                list_out = StringIO()
                call_command('list_price_candidates', stdout=list_out)
                self.assertEqual([row['source_record_id'] for row in json.loads(list_out.getvalue())['data']], ['cli-1'])
            finally:
                os.unlink(csv_path)
