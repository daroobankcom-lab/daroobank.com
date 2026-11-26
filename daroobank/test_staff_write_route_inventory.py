"""Inventory of staff routes and which in-flight guard tests cover them.

This is a drift guard, not a security proof: it fails when a staff route appears
without an explicit classification, and when a route claimed as covered is not
actually named in the test module claimed to cover it. It says nothing about the
quality of those tests, and the guards themselves remain partial mitigations
(ADR 0191-0198).
"""
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import get_resolver

# Route name -> module holding a synchronized in-flight write test for it.
COVERED_WRITE_ROUTES = {
    'staff_source_create': 'daroobank/test_staff_inflight_write.py',
    'staff_source_review': 'daroobank/test_staff_inflight_write.py',
    'staff_price_review': 'daroobank/test_staff_inflight_review_writes.py',
    'staff_clinical_review': 'daroobank/test_staff_inflight_review_writes.py',
    'staff_product_review': 'daroobank/test_staff_inflight_review_writes.py',
    'staff_product_upload': 'daroobank/test_staff_inflight_stage_writes.py',
    'staff_price_upload': 'daroobank/test_staff_inflight_stage_writes.py',
    'staff_clinical_create': 'daroobank/test_staff_inflight_clinical_writes.py',
    'staff_clinical_reference_create': 'daroobank/test_staff_inflight_clinical_writes.py',
    'staff_clinical_revise': 'daroobank/test_staff_inflight_revision_writes.py',
    'staff_identity_create': 'daroobank/test_staff_inflight_identity_writes.py',
    'staff_identity_review': 'daroobank/test_staff_inflight_identity_writes.py',
    'staff_identity_revise': 'daroobank/test_staff_inflight_revision_writes.py',
    'staff_identity_revise_component': 'daroobank/test_staff_inflight_revision_writes.py',
}

# Route name -> why no in-flight write test applies.
NON_WRITE_ROUTES = {
    'staff_workspace': 'read-only index',
    'staff_login': 'authentication entry point, covered by revocation boundary tests',
    'staff_logout': 'session teardown, covered by revocation boundary tests',
    'staff_sources': 'read-only list',
    'staff_source_detail': 'read-only detail',
    'staff_source_date_inspection': 'read-only inspection',
    'staff_source_review_inspection': 'read-only inspection',
    'staff_products': 'read-only list',
    'staff_product_detail': 'read-only detail',
    'staff_product_review_inspection': 'read-only inspection',
    'staff_product_sample': 'static sample download',
    'staff_prices': 'read-only list',
    'staff_price_detail': 'read-only detail',
    'staff_price_review_inspection': 'read-only inspection',
    'staff_price_sample': 'static sample download',
    'staff_clinical_drafts': 'read-only list',
    'staff_clinical_detail': 'read-only detail',
    'staff_clinical_inspection': 'read-only inspection',
    'staff_clinical_review_inspection': 'read-only inspection',
    'staff_clinical_lineage': 'read-only lineage',
    'staff_identity_list': 'read-only list',
    'staff_identity_detail': 'read-only detail',
    'staff_identity_lineage': 'read-only lineage',
    'staff_catalog_quality': 'read-only quality queue',
    'staff_catalog_quality_irc': 'read-only IRC inspection',
    'staff_import_receipts': 'read-only receipt list',
    'staff_import_receipt_detail': 'read-only receipt detail',
    'staff_import_manifest_inspection': 'read-only manifest inspection',
    'staff_ingestion_window': 'read-only limiter window',
}

ROOT = Path(__file__).resolve().parent.parent


def staff_route_names():
    return {name for name in get_resolver().reverse_dict if isinstance(name, str) and name.startswith('staff_')}


class StaffWriteRouteInventoryTests(SimpleTestCase):
    def test_every_staff_route_is_classified(self):
        names = staff_route_names()
        classified = set(COVERED_WRITE_ROUTES) | set(NON_WRITE_ROUTES)
        self.assertEqual(names - classified, set(),
                         'New staff routes need an in-flight write test or an explicit classification.')
        self.assertEqual(classified - names, set(),
                         'Classified staff routes no longer exist; update the inventory.')
        self.assertEqual(set(COVERED_WRITE_ROUTES) & set(NON_WRITE_ROUTES), set())

    def test_covered_routes_are_named_by_their_claimed_test_module(self):
        for route, relative in sorted(COVERED_WRITE_ROUTES.items()):
            with self.subTest(route=route):
                source = (ROOT / relative).read_text(encoding='utf-8')
                self.assertIn(route, source, f'{relative} no longer references {route}.')
                self.assertIn('invalidate_and_reactivate', source,
                              f'{relative} no longer parks a write around a password invalidation.')

    def test_inventory_documents_a_partial_mitigation(self):
        # The covered guards deny a credential change committed before the recheck;
        # they are not durable revocation of an in-flight write, which the session
        # guard handles at the request boundary (ADR 0213), and a parked write whose
        # flags were only toggled can still commit.
        security = (ROOT / 'docs' / 'SECURITY.md').read_text(encoding='utf-8')
        self.assertIn('not durable revocation', security.lower().replace('**', ''))
        self.assertIn('0191-staff-session-revocation-gap.md', security)
