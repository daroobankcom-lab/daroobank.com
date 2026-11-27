"""The API and permissions plan, and what this boundary enforces on the live runtime.

`docs/API_PERMISSIONS_PLAN.md` exists because seven sources govern or expose this
repository's API, sessions and permission boundary without signing off its rules or
measuring everything outside the parity suites. This suite keeps twelve database-free
(`SimpleTestCase`) invariant checks and two live PostgreSQL 16.2 (`TransactionTestCase`)
tests pinning the plan to the live tree:

* 55 named routes (43 `staff_*` under `STAFF_PORTAL_ENABLED = DEBUG`, 12 non-staff including
  3 `/api/v1/*` and 2 `health_*`), with **0** `@permission_required` or `@staff_member_required`
  decorators (`36` inline, `2` `scan_response`-delegated, `3` downstream-service `inspect_lineage`/
  `inspect_manifest` guards, `2` decorator-free auth CBVs, `2` decorator-free health probes);
* 36 `all of`, 4 `any of` and 1 `is_staff`-only matrix route using 16 of 63 `auth_permission` rows,
  `StaffLoginView` accepting `PUT` (HTTP 200, unauthenticated) and overriding `LOGIN_REDIRECT_URL`;
* closed parity, CSRF, method-sweep, header and cursor/token inventories (`23` `OBJECT_ROUTES`, `13`
  identifier shapes, `9` caller query shapes with `KIND_FILTER_ROUTE = 'staff_import_receipts'`,
  `5` CSRF failure shapes separating `27` safe-only / `9` dual / `5` POST-only routes, `5`
  `EXPECTED_ALLOW` strings across `1,204` responses with `7` pinned and `9` variable headers,
  `4` `loads_nonfuture` signed cursors + `1` repair token + `0` API tokens);
* `docs/openapi.json` (3 paths, 0 headers, 0 `securitySchemes`, missing parameter bounds and error
  code enum) vs `docs/API_DESIGN.md`'s 11 unbuilt paths and live HTTP drift (`8` headers, HTML
  405/403/429, 120-char `q` slicing before `\x00` validation, `4,300`/`4,301`-digit JSON/HTML split);
* active superusers bypassing 41/41 routes, sequential `Group` equivalence with no exclusivity or
  lock protection, 16-permission accumulation, 0 of 37 `CHECK` constraints enforcing SoD,
  cross-revision self-review in `clinical` and `catalog.identity`, 15 of 16 `lock=False`
  `recheck_actor` calls (`sources.review_claim` committing after deactivation + password rotation),
  ADR 0191 residual blockers and `5,000`-row session caps, `0` non-test `HTTP_X_FORWARDED_FOR`
  readers referencing lane 2 (`docs/NETWORK_TLS_PLAN.md`), 6 non-debug CLI commands and `LOGGING == {}`.

All checks are synthetic measurements; nothing here approves endpoints or replaces an owner's
decision in `docs/AUTHORIZATION_REVIEW.md`.
"""
import ast
import inspect
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
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.management import CommandError, call_command, get_commands
from django.db import OperationalError, close_old_connections, connection
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import get_resolver, reverse
from django.utils import timezone as dj_timezone

from catalog import identity_lineage, projection_repair, quality_irc, services as catalog_services
from catalog.identity import (create_formulation, create_ingredient, create_package, create_product,
                              digest as identity_digest, package_snapshot, review_package,
                              revise_package)
from catalog.intake import stage_products
from catalog.models import ProductCandidate, ProductPresentation
from catalog.services import MAX_QUERY_LENGTH
from clinical import lineage as clinical_lineage
from clinical.evidence import evidence_state
from clinical.services import create_draft, review_draft
from daroobank import authorization_review, session_guard
from daroobank.actor_recheck import recheck_actor
from daroobank.middleware import PublicReadLimitMiddleware
from daroobank.session_guard import authorization_fingerprint
from daroobank.signed_cursors import loads_nonfuture
from daroobank.test_public_route_privacy_matrix import PUBLIC_HEADER_ROUTES, PUBLIC_ROUTES
from daroobank.test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS
from daroobank.test_staff_authorization_objects import OBJECT_ROUTES
from daroobank.test_staff_csrf_gate import DUAL_METHOD_ROUTES, POST_ONLY_ROUTES
from daroobank.test_staff_denial_parity import VOLATILE_HEADERS
from daroobank.test_staff_header_inventory import ALLOW_VALUES, PINNED_HEADERS, SAMPLE_ROUTES, VARIABLE_HEADERS
from daroobank.test_staff_identifier_parity import (DUAL_METHOD_ROUTES as ID_DUAL_ROUTES,
                                                   NON_MATCHING, RESOLVING)
from daroobank.test_staff_method_sweep import DESTRUCTIVE, EXPECTED_ALLOW, METHODS
from daroobank.test_staff_query_parity import KIND_FILTER_ROUTE, QUERY_VARIANTS
from ingestion.models import ImportReceipt, ImportReceiptItem
from pricing.importer import stage_csv as stage_price_csv
from pricing.models import PriceCandidate
from sources.models import SourceClaimReview
from sources.services import _lock_latest_review, record_claim, review_claim

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'API_PERMISSIONS_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0235-api-permissions-plan.md'
ADR_0191 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0191-staff-session-revocation-gap.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
OPENAPI = ROOT / 'docs' / 'openapi.json'
API_DESIGN = ROOT / 'docs' / 'API_DESIGN.md'
AUTHORIZATION_REVIEW = ROOT / 'docs' / 'AUTHORIZATION_REVIEW.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
NETWORK_TLS_PLAN = ROOT / 'docs' / 'NETWORK_TLS_PLAN.md'
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
    'The URL surface, decorator enforcement versus test-asserted authorization, and login behavior',
    'Denial shapes, identifier and query parity, CSRF gate, method sweep and closed header inventory',
    'Public API contract versus live behavior, and cursor and token shapes',
    'Superuser bypass, group grants, single-user accumulation and separation-of-duties boundaries',
    'In-flight locking, ADR 0191 blockers, proxy `REMOTE_ADDR`, CLI and audit boundaries',
]
DECISIONS = [
    'Expose more of the sketched API or keep the three read endpoints — and what replaces `STAFF_PORTAL_ENABLED = DEBUG`?',
    'Enforce endpoint/object permissions for future API endpoints, and approve the current 41-route matrix and 47 unreferenced permissions?',
    'Settle whether `is_superuser` keeps its staff bypass, or must clinical, source and catalog review deny superusers without explicit scoped grants?',
    'May one account accumulate author and reviewer permissions (directly or via groups), or must mutually exclusive roles be enforced at grant time and in the database?',
    'Should separation of duties extend across revision lineages and into PostgreSQL constraints, or stay bound to immediate drafts and graphs?',
    'Reconcile OpenAPI (`docs/openapi.json`) against live error, header and throttle behavior — or defer contract alignment?',
    'Which authentication scheme, scoping and revocation boundary applies to institutional and mobile API clients?',
    "How are ADR 0191's residual blockers (dormant sessions beyond 5,000 rows, unlocked in-flight rechecks), unauthenticated non-debug CLI commands and missing audit logs closed?",
]
OPTIONS = [
    'A. Leave the API and permission boundary as documented',
    'B. Keep the 3 read endpoints only and reconcile `docs/openapi.json` against live error, header and throttle behavior',
    'C. Settle `is_superuser` bypass, block user/group add+review accumulation, harden `StaffLoginView` and promote downstream service guards to view entry',
    'D. Enforce lineage-wide separation of duties, lock-ordered `recheck_actor` across user/group tables, and PostgreSQL `CHECK` or trigger constraints',
    'E. Expose the sketched institutional/v1 endpoints with scoped tokens and endpoint/object permission enforcement',
    'F. Decouple staff portal activation from `DEBUG` and close ADR 0191\'s residual gaps, the 5,000-row scan bound and CLI bypass',
    'G. Defer authenticated APIs and production staff portal out of Phase 1, leaving only the 3 read endpoints',
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
    (ADR_0191, 'the revival scenario named below is closed by'),
    (ADR_0191, 'a transition no request observes (which is what the `revoke_staff_sessions` command is for), in-flight requests that already passed the guard, backend removal from settings, MFA, replay protection, session inventory and any production procedure'),
    (NETWORK_TLS_PLAN, '`HTTP_X_FORWARDED_FOR` is read by 0 non-test modules'),
    (DEPLOYMENT, 'Rate and size limits still have to be provisioned by the reverse proxy, a CDN or the host before this service faces the public internet'),
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
HELPER_DELEGATED_ROUTES = frozenset({'staff_product_review_inspection', 'staff_price_review_inspection'})
SERVICE_DELEGATED_ROUTES = frozenset({
    'staff_clinical_lineage',
    'staff_identity_lineage',
    'staff_import_manifest_inspection',
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
            if not path.name.startswith('test_') and path.name != 'tests.py'
            and 'tools' not in path.relative_to(ROOT).parts]


def command_modules():
    return [path for path in project_modules()
            if 'management/commands' in path.relative_to(ROOT).as_posix()
            and path.name != '__init__.py']


def walk_resolver(resolver=None, prefix=''):
    if resolver is None:
        resolver = get_resolver()
    for entry in resolver.url_patterns:
        if hasattr(entry, 'url_patterns'):
            yield from walk_resolver(entry, prefix + str(entry.pattern))
        elif entry.name is not None:
            yield entry.name, prefix + str(entry.pattern), entry.callback


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
                      '16 permissions', '63 rows', '47 rows',
                      '41/41', '37 `CHECK` constraints', '15 of 16 `recheck_actor` sites',
                      '5,000', '6 of 12 management commands', '120', '4,300', '4,301',
                      '179', '25,938', '1,709', 'Retry-After: 60', 'LOGGING == {}',
                      '`23` `OBJECT_ROUTES`', '`1,204` responses', 'HTTP_X_FORWARDED_FOR'):
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
    def test_resolver_and_decorator_vs_service_enforcement_inventory(self):
        entries = list(walk_resolver())
        names = {name for name, _pat, _cb in entries}
        staff_names = {name for name in names if name.startswith('staff_')}
        public_names = {name for name in names if not name.startswith('staff_')}
        self.assertEqual(len(entries), 55)
        self.assertEqual(len(staff_names), 43)
        self.assertEqual(len(public_names), 12)
        self.assertEqual(len(ROUTES), 41)
        self.assertEqual(len(ALL_PERMISSIONS), 16)
        self.assertEqual(len(VIEW_PERMISSIONS), 6)

        by_app = {}
        perm_decorators = []
        login_required_count = 0
        safe_count = 0
        dual_count = 0
        post_count = 0
        cbv_names = set()
        health_names = set()
        inline_routes = set()
        helper_routes = set()
        service_routes = set()
        for name, _pat, cb in entries:
            app = cb.__module__.split('.')[0]
            by_app[app] = by_app.get(app, 0) + 1
            fn = getattr(cb, 'view_class', cb)
            src = inspect.getsource(fn)
            node = ast.parse(src).body[0]
            decs = [ast.unparse(d) for d in getattr(node, 'decorator_list', [])]
            if any('permission_required' in d or 'staff_member_required' in d for d in decs):
                perm_decorators.append(name)
            if any('login_required' in d for d in decs):
                login_required_count += 1
            if any('require_safe' in d for d in decs):
                safe_count += 1
            if any('require_http_methods' in d for d in decs):
                dual_count += 1
            if any('require_POST' in d for d in decs):
                post_count += 1
            if hasattr(cb, 'view_class'):
                cbv_names.add(name)
                continue
            if not name.startswith('staff_'):
                if not decs:
                    health_names.add(name)
                continue
            early_src = '\n'.join(ast.unparse(stmt) for stmt in node.body[:6])
            if any(tok in early_src for tok in ('require_staff', '_require_permission', 'visible_kinds', 'is_staff')):
                inline_routes.add(name)
            elif 'scan_response' in src:
                helper_routes.add(name)
            elif 'inspect_lineage' in src or 'inspect_manifest' in src:
                service_routes.add(name)

        self.assertEqual(by_app, {'daroobank': 3, 'catalog': 25, 'pricing': 8, 'ingestion': 4, 'clinical': 9, 'sources': 6})
        self.assertEqual(perm_decorators, [])
        self.assertEqual(login_required_count, 41)
        self.assertEqual((safe_count, dual_count, post_count), (37, 9, 5))
        self.assertEqual(cbv_names, {'staff_login', 'staff_logout'})
        self.assertEqual(health_names, {'health_live', 'health_ready'})
        self.assertEqual(len(inline_routes), 36)
        self.assertEqual(helper_routes, HELPER_DELEGATED_ROUTES)
        self.assertEqual(service_routes, SERVICE_DELEGATED_ROUTES)

        # In ingestion/staff_views.py:manifest_inspection, parse_scan_after runs before inspect_manifest.
        from ingestion.staff_views import manifest_inspection
        m_src = inspect.getsource(manifest_inspection)
        self.assertLess(m_src.index('parse_scan_after('), m_src.index('inspect_manifest('))

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

    def test_denial_parity_csrf_method_sweep_and_header_inventory_shapes(self):
        self.assertEqual(len(OBJECT_ROUTES), 23)
        self.assertEqual(len(ID_DUAL_ROUTES), 4)
        self.assertEqual(len(OBJECT_ROUTES) - len(ID_DUAL_ROUTES), 19)
        self.assertEqual((len(RESOLVING), len(NON_MATCHING)), (4, 9))
        self.assertEqual(len(QUERY_VARIANTS), 9)
        self.assertEqual(KIND_FILTER_ROUTE, 'staff_import_receipts')
        self.assertEqual((len(POST_ONLY_ROUTES), len(DUAL_METHOD_ROUTES)), (5, 9))
        self.assertEqual(len(ROUTES) - len(POST_ONLY_ROUTES) - len(DUAL_METHOD_ROUTES), 27)
        self.assertEqual(METHODS, ('GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'DELETE'))
        self.assertEqual(DESTRUCTIVE, ('PUT', 'PATCH', 'DELETE'))
        self.assertEqual(sorted(ALLOW_VALUES), [
            'GET, HEAD', 'GET, POST', 'GET, POST, PUT, HEAD, OPTIONS', 'POST', 'POST, OPTIONS',
        ])
        self.assertEqual(len(EXPECTED_ALLOW), 5)
        self.assertEqual(len(PINNED_HEADERS), 7)
        self.assertEqual(len(VARIABLE_HEADERS), 9)
        self.assertEqual(len(VOLATILE_HEADERS), 3)
        self.assertEqual(sorted(SAMPLE_ROUTES), ['staff_price_sample', 'staff_product_sample'])
        self.assertEqual(43 * (len(METHODS) + 1) * 4, 1204)
        self.assertEqual(len(PUBLIC_ROUTES), 17)
        self.assertEqual(len(PUBLIC_HEADER_ROUTES), 5)
        self.assertIn('XFrameOptionsMiddleware', read(SETTINGS))

    def test_signed_cursors_session_tokens_and_proxy_remote_addr_boundary(self):
        cursor_specs = (
            (catalog_services, 'catalog.search.cursor.v1', 3600, 512),
            (quality_irc, 'catalog.quality.irc.cursor.v1', 3600, 512),
            (identity_lineage, 'catalog.identity.lineage.v1', 3600, 1024),
            (clinical_lineage, 'clinical.draft.lineage.v1', 3600, 1024),
        )
        for mod, salt, age, maxlen in cursor_specs:
            self.assertEqual(mod.CURSOR_SALT, salt)
            self.assertEqual(mod.CURSOR_MAX_AGE, age)
            self.assertEqual(mod.MAX_CURSOR_LENGTH, maxlen)
        self.assertEqual(projection_repair.SALT, 'catalog.synthetic-projection-repair.v1')
        self.assertEqual((projection_repair.TOKEN_AGE, projection_repair.MAX_TOKEN_LENGTH), (600, 512))
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertFalse(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertEqual(session_guard._KEY_SALT, 'daroobank.staff.session.v1')

        # Compressed cursor and future-timestamp rejection without DB.
        compressed = signing.dumps({'payload': 'x' * 5000}, salt=catalog_services.CURSOR_SALT, compress=True)
        self.assertTrue(compressed.startswith('.'))
        with self.assertRaises(catalog_services.InvalidSearchCursor):
            catalog_services._decode_cursor(compressed, 'a', None)
        with patch('django.core.signing.time.time', return_value=2_000_000_000):
            future = signing.dumps({'k': 'v'}, salt='synthetic-future-test')
        with self.assertRaises(signing.BadSignature):
            loads_nonfuture(future, salt='synthetic-future-test', max_age=3600)

        bearer_reads = []
        xff_reads = []
        for path in project_modules():
            src = read(path)
            rel = path.relative_to(ROOT).as_posix()
            if 'HTTP_AUTHORIZATION' in src or 'Bearer' in src:
                bearer_reads.append(rel)
            if 'HTTP_X_FORWARDED_FOR' in src:
                xff_reads.append(rel)
        self.assertEqual(bearer_reads, [])
        self.assertEqual(xff_reads, [])
        self.assertIn("request.META.get('REMOTE_ADDR')", inspect.getsource(PublicReadLimitMiddleware))
        self.assertIn("request.META.get('REMOTE_ADDR')", read(ROOT / 'pricing' / 'staff_views.py'))

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
        self.assertGreaterEqual(len(red_rows), 20)
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

    def test_live_http_api_contract_denials_csrf_methods_headers_and_grants(self):
        self._create_published_presentation()
        client = Client()
        # Ensure middleware (and thus user_logged_in._bind_fingerprint) is active before force_login calls.
        self.assertEqual(client.get('/').status_code, 200)

        # 1. Public API contract drift & rate limiting.
        r_trunc = client.get('/api/v1/search/', {'q': ('a' * MAX_QUERY_LENGTH) + 'ZZZZ_IGNORED'})
        self.assertEqual(r_trunc.status_code, 200)
        self.assertEqual(len(r_trunc.json()['data']), 1)

        r_ctrl_inside = client.get('/api/v1/search/', {'q': ('a' * 10) + '\x00'})
        self.assertEqual(r_ctrl_inside.status_code, 400)
        self.assertEqual(r_ctrl_inside.json()['error']['code'], 'invalid_query')

        r_ctrl_past = client.get('/api/v1/search/', {'q': ('a' * MAX_QUERY_LENGTH) + '\x00'})
        self.assertEqual(r_ctrl_past.status_code, 200)

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

        r_spec = client.get('/api/v1/openapi.json')
        self.assertEqual(r_spec.status_code, 200)
        self.assertEqual(sorted(r_spec.headers.keys()), [
            'Cache-Control', 'Content-Length', 'Content-Security-Policy', 'Content-Type',
            'Cross-Origin-Opener-Policy', 'Referrer-Policy', 'X-Content-Type-Options', 'X-Robots-Tag',
        ])

        csrf_client = Client(enforce_csrf_checks=True)
        with self.assertLogs('django.security.csrf', level='WARNING'):
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

        # 2. Canonical denial shapes across account shapes, view vs service delegation, CSRF & login.
        User = get_user_model()
        outsider = User.objects.create_user('api-plan-outsider', password='synthetic-password-1234')
        bare = User.objects.create_user('api-plan-bare', password='synthetic-password-1234', is_staff=True)
        super_staff = User.objects.create_user('api-plan-super', password='synthetic-password-1234',
                                               is_staff=True, is_superuser=True)
        super_nonstaff = User.objects.create_user('api-plan-super-ns', password='synthetic-password-1234',
                                                  is_staff=False, is_superuser=True)
        r_anon = client.get(reverse('staff_products'))
        self.assertEqual((r_anon.status_code, len(r_anon.content), r_anon.headers['Location']),
                         (302, 0, '/staff/login/?next=/staff/products/'))
        self.assertEqual(len(r_anon.headers), 11)

        denial_bodies = set()
        for account in (outsider, bare, super_nonstaff):
            c_acc = Client()
            c_acc.force_login(account)
            with self.assertLogs('django.request', level='WARNING'):
                for url in (
                    reverse('staff_products'),
                    reverse('staff_product_review_inspection', kwargs={'pk': 999999999}) + '?after=abc',
                    reverse('staff_clinical_lineage', kwargs={'pk': 999999999}) + '?cursor=bad',
                    reverse('staff_identity_lineage', kwargs={'kind': 'package', 'pk': 999999999}) + '?cursor=bad',
                    reverse('staff_import_manifest_inspection', kwargs={'pk': 999999999}) + '?after=abc&category=%00',
                ):
                    resp = c_acc.get(url)
                    self.assertEqual((resp.status_code, len(resp.content)), (403, 135))
                    denial_bodies.add(resp.content)
        self.assertEqual(len(denial_bodies), 1)

        with self.assertLogs('django.security.csrf', level='WARNING'):
            with override_settings(DEBUG=True):
                c_dbg = Client(enforce_csrf_checks=True)
                self.assertEqual(len(c_dbg.post('/staff/products/', {}).content), 3174)
                c_dbg.get('/staff/login/')
                self.assertEqual(len(c_dbg.post('/staff/products/', {}).content), 2504)
            with override_settings(DEBUG=False):
                c_nodbg = Client(enforce_csrf_checks=True)
                self.assertEqual(len(c_nodbg.post('/staff/products/', {}).content), 1709)
                c_nodbg.get('/staff/login/')
                self.assertEqual(len(c_nodbg.post('/staff/products/', {}).content), 1040)

        # 3. Superuser bypass (41/41), group grants, and StaffLoginView PUT / redirect override.
        self.assertEqual(super_staff.user_permissions.count(), 0)
        self.assertEqual(super_staff.groups.count(), 0)
        c_super = Client()
        c_super.force_login(super_staff)
        c_nonstaff = Client()
        c_nonstaff.force_login(super_nonstaff)
        with self.assertLogs('django.request', level='WARNING'):
            for name, kwargs, method, _req in ROUTES:
                url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
                r_ok = c_super.get(url) if method == 'GET' else c_super.post(url, {})
                self.assertNotEqual(r_ok.status_code, 403, f'superuser denied on {name}')
                r_no = c_nonstaff.get(url) if method == 'GET' else c_nonstaff.post(url, {})
                self.assertEqual(r_no.status_code, 403, f'non-staff superuser allowed on {name}')

        full_group = Group.objects.create(name='api-plan-full-group')
        full_group.permissions.set(Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        group_user = User.objects.create_user('api-plan-group-user', password='synthetic-password-1234', is_staff=True)
        group_user.groups.add(full_group)
        stale_group_user = User.objects.get(pk=group_user.pk)
        self.assertTrue(stale_group_user.has_perm('sources.view_sourceclaim'))
        group_user.groups.remove(full_group)
        self.assertTrue(stale_group_user.has_perm('sources.view_sourceclaim'))
        with self.assertRaises(Exception):
            recheck_actor(stale_group_user, 'sources.view_sourceclaim')
        c_grp = Client()
        c_grp.force_login(group_user)
        self.assertEqual(c_grp.get(reverse('staff_workspace')).status_code, 200)
        User.objects.filter(pk=group_user.pk).update(is_active=False)
        r_flushed = c_grp.get(reverse('staff_products'))
        self.assertEqual((r_flushed.status_code, r_flushed.headers['Location']),
                         (302, '/staff/login/?next=/staff/products/'))

        login_url = reverse('staff_login')
        self.assertEqual(c_nonstaff.get(login_url).status_code, 200)
        put_client = Client()
        self.assertEqual(put_client.put(login_url).status_code, 200)
        self.assertNotIn('_auth_user_id', put_client.session)

        login_client = Client()
        r_login = login_client.post(login_url, {'username': 'api-plan-super', 'password': 'synthetic-password-1234'})
        self.assertEqual((r_login.status_code, r_login.headers['Location']), (302, '/staff/'))

    def test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary(self):
        User = get_user_model()
        self.assertEqual(Permission.objects.count(), 63)

        # 1. 0 of 37 PostgreSQL CHECK constraints reference user/actor/reviewer columns.
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

        super_staff = User.objects.create_user('api-plan-sod-super', password='synthetic-password-1234',
                                               is_staff=True, is_superuser=True)
        accumulated = User.objects.create_user('api-plan-accumulated', password='synthetic-password-1234',
                                               is_staff=True)
        reviewer = User.objects.create_user('api-plan-reviewer', password='synthetic-password-1234',
                                            is_staff=True)
        all_perms = list(Permission.objects.filter(codename__in=[codename for _app, codename in ALL_PERMISSIONS]))
        accumulated.user_permissions.add(*all_perms)
        reviewer.user_permissions.add(*all_perms)
        self.assertEqual(accumulated.user_permissions.count(), 16)

        # 2. Direct self-review fails closed (403) across 5 domains, yet v1->v2 revision review succeeds.
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

        c_super = Client()
        c_super.get('/')
        c_super.force_login(super_staff)
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

        draft_v2 = create_draft(
            actor=accumulated, data={**draft_data, 'statement': 'نسخه دوم با ویرایش همکار'},
            parent_id=draft_v1.pk, expected_parent_hash=draft_v1.payload_sha256,
            change_reason='اصلاح متنی نسخه دوم',
        )
        self.assertIsNotNone(review_draft(
            actor=super_staff, draft_id=draft_v2.pk, decision='further_review',
            reason='نویسنده نسخه اول در حال بررسی نسخه دوم است.',
            expected_review=0, expected_hash=draft_v2.payload_sha256,
        ).pk)

        pkg_v2 = revise_package(
            actor=accumulated, parent_id=pkg_v1.pk,
            data={'description': '20 عدد', 'quantity': Decimal('20.0000'), 'quantity_unit': 'tablet',
                  'irc': '223', 'source_name': 'منبع', 'source_url': 'https://example.org/pkg2'},
            change_reason='اصلاح توضیح بسته‌بندی در نسخه دوم',
            expected_graph_hash=pkg1_hash, expected_review=0,
        )
        self.assertIsNotNone(review_package(
            actor=super_staff, package_id=pkg_v2.pk, decision='reject',
            reason='ثبت‌کننده بسته قبلی در حال بازبینی نسخه اصلاح‌شده است.',
            expected_review=0, expected_graph_hash=identity_digest(package_snapshot(pkg_v2)),
        ).pk)

        # 3. Dormant session survival across off/on toggle and 5,000-row scan cap.
        c = Client()
        c.force_login(accumulated)
        self.assertEqual(c.get(reverse('staff_workspace')).status_code, 200)
        fp_before = authorization_fingerprint(accumulated.pk)
        User.objects.filter(pk=accumulated.pk).update(is_active=False)
        self.assertEqual(c.get('/api/v1/openapi.json').status_code, 200)
        User.objects.filter(pk=accumulated.pk).update(is_active=True)
        self.assertEqual(authorization_fingerprint(accumulated.pk), fp_before)
        self.assertEqual(c.get(reverse('staff_workspace')).status_code, 200)

        Session.objects.all().delete()
        target_key = 'z' * 32
        other_payload = SessionStore().encode({'_auth_user_id': str(reviewer.pk), '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend'})
        acc_payload = SessionStore().encode({'_auth_user_id': str(accumulated.pk), '_auth_user_backend': 'django.contrib.auth.backends.ModelBackend'})
        exp = datetime(2030, 1, 1, tzinfo=timezone.utc)
        Session.objects.bulk_create(
            [Session(session_key=f'0000{idx:028d}', session_data=other_payload, expire_date=exp) for idx in range(5000)]
            + [Session(session_key=target_key, session_data=acc_payload, expire_date=exp)]
        )
        with override_settings(DEBUG=True):
            out_list = StringIO()
            call_command('list_staff_sessions', '--username', 'api-plan-accumulated', stdout=out_list)
            listed = json.loads(out_list.getvalue())
            self.assertEqual((listed['scanned'], listed['sessions_matched']), (5000, 0))
            out_rev = StringIO()
            call_command('revoke_staff_sessions', '--username', 'api-plan-accumulated', '--apply', stdout=out_rev)
            revoked = json.loads(out_rev.getvalue())
            self.assertEqual((revoked['scanned'], revoked['matched'], revoked['revoked']), (5000, 0, 0))
            self.assertTrue(Session.objects.filter(session_key=target_key).exists())

        # 4. Unlocked recheck_actor race vs lock=True blocking auth_user only (not user_permissions / groups).
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
                return record_claim(actor=User.objects.get(pk=accumulated.pk), data={
                    'source_name': 'منبع قفل', 'source_url': 'https://example.org/locked',
                    'owner': 'ناشر', 'evidence_url': 'https://example.org/locked-ev', 'evidence_note': '',
                    'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
                    'starts_on': None, 'expires_on': None,
                })
            finally:
                close_old_connections()

        lock_group = Group.objects.create(name='api-plan-lock-group')
        accumulated.groups.add(lock_group)
        with patch('sources.services._find_or_create_claim', side_effect=pause_locked):
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(locked_writer)
                try:
                    self.assertTrue(lock_ready.wait(10))
                    with connection.cursor() as cur:
                        cur.execute("SET lock_timeout = '200ms'")
                        with self.assertRaises(OperationalError) as ctx:
                            User.objects.filter(pk=accumulated.pk).update(is_active=False)
                        self.assertEqual(getattr(ctx.exception.__cause__, 'sqlstate', None), '55P03')
                        cur.execute('SET lock_timeout = 0')
                    # Direct and group M2M permission tables do not block on the auth_user row lock.
                    accumulated.user_permissions.clear()
                    accumulated.groups.clear()
                finally:
                    lock_resume.set()
                _, created_locked = fut.result(timeout=15)
        self.assertTrue(created_locked)

        # 5. Non-debug CLI execution vs debug-only commands.
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
                self.assertEqual({row['source_record_id'] for row in json.loads(list_out.getvalue())['data']},
                                 {'sr-1', 'cli-1'})
            finally:
                os.unlink(csv_path)
