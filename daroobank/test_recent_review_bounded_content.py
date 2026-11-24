"""Synthetic large review records in private recent-history detail pages."""
from datetime import date

from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from clinical.evidence import evidence_state
from clinical.models import ClinicalDraftReview
from clinical.services import create_draft, review_draft
from . import test_recent_review_history as fixtures
from .review_history import recent_reviews_with_reviewers


@override_settings(STAFF_PORTAL_ENABLED=True)
class RecentReviewBoundedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RecentReviewHistoryTests.setUpTestData.__func__(cls)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        cls.viewer.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        for user in (cls.author, cls.reviewer, cls.viewer):
            for attr in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
                if hasattr(user, attr):
                    delattr(user, attr)
        cls.draft = create_draft(actor=cls.author, data={
            'subject': 'موضوع ساختگی', 'audience': 'patient', 'title': 'عنوان ساختگی',
            'statement': 'متن ساختگی برای آزمون', 'reference_title': 'مرجع ساختگی',
            'reference_url': 'https://example.org/clinical', 'reference_location': 'بخش ساختگی',
            'reference_author': '', 'reference_version': '', 'reference_published_on': date(2025, 1, 2),
            'reference_accessed_on': None})
        cls.clinical_event = review_draft(actor=cls.reviewer, draft_id=cls.draft.pk, decision='defer',
            reason=cls.reason, expected_review=0, expected_hash=cls.draft.payload_sha256,
            expected_evidence_hash=evidence_state(cls.draft)['fingerprint'])

    def cases(self):
        return [(d, item, event, model, detail) for d, item, event, model, detail, _, _
                in fixtures.RecentReviewHistoryTests.cases(self)] + [
                    ('clinical', self.draft, self.clinical_event, ClinicalDraftReview, 'staff_clinical_detail')]

    def test_oversized_content_is_not_transferred_or_rendered_and_keeps_latest_token(self):
        self.client.force_login(self.reviewer)
        for domain, parent, event, model, route in self.cases():
            with self.subTest(domain=domain):
                model.objects.filter(pk=event.pk).update(review_snapshot={'private-canary': 'آ' * 1_000_000},
                    reason='ر' * 100_000 + 'reason-private-canary')
                with CaptureQueriesContext(connection) as queries:
                    rows = recent_reviews_with_reviewers(parent.reviews.all())
                self.assertEqual(len(queries), 2)
                self.assertTrue(rows[0].review_snapshot is None, 'oversized JSON must not be returned')
                self.assertIsNone(rows[0].reason)
                self.assertEqual(len(rows[0]._bounded_reason), 1001)
                self.assertTrue(rows[0].content_oversized)
                self.assertEqual(rows[0].get_deferred_fields(), set())
                sql = queries[0]['sql']
                self.assertIn('LIMIT 25', sql)
                self.assertNotRegex(sql.split(' FROM ', 1)[0].lower(),
                    rf'(?:^select |, )"{model._meta.db_table}"\."(?:reason|review_snapshot)"(?:,|$)')
                response = self.client.get(reverse(route, args=[parent.pk]))
                self.assertEqual(response.status_code, 200)
                row = response.context['reviews'][0]
                self.assertEqual(row.technical_status, 'oversized')
                self.assertContains(response, 'بیش از حد نمایش')
                self.assertNotContains(response, 'private-canary')
                self.assertNotContains(response, 'reason-private-canary')
                self.assertEqual(response.context['review_form'].initial['expected_review'], event.pk)
                self.assertIn('no-store', response['Cache-Control'])
                event.refresh_from_db()
                self.assertEqual(len(event.reason), 100_000 + len('reason-private-canary'))

    def test_reason_only_large_and_valid_neighbour_remains_visible(self):
        self.client.force_login(self.viewer)
        for domain, parent, event, model, route in self.cases():
            with self.subTest(domain=domain):
                values = {f.attname: getattr(event, f.attname) for f in model._meta.concrete_fields
                          if f.name not in ('id', 'created_at')}
                second = model.objects.create(**values)
                model.objects.filter(pk=event.pk).update(reason='private-reason-canary' + 'ر' * 100_000)
                response = self.client.get(reverse(route, args=[parent.pk]))
                self.assertEqual([r.pk for r in response.context['reviews']], [second.pk, event.pk])
                self.assertEqual(response.context['reviews'][0].technical_status, 'consistent')
                self.assertEqual(response.context['reviews'][1].technical_status, 'oversized')
                self.assertContains(response, self.reason)
                self.assertNotContains(response, 'private-reason-canary')

    def test_exact_thresholds_and_small_malformed_values(self):
        from django.db.models import JSONField, TextField, Value
        from django.db.models.functions import Cast, Length
        self.client.force_login(self.viewer)
        for domain, parent, event, model, route in self.cases():
            with self.subTest(domain=domain):
                for size in (1000, 1001):
                    model.objects.filter(pk=event.pk).update(review_snapshot=event.review_snapshot, reason='ر' * size)
                    response = self.client.get(reverse(route, args=[parent.pk]))
                    self.assertEqual(response.context['reviews'][0].technical_status,
                                     'consistent' if size == 1000 else 'oversized')
                for size in (65536, 65537):
                    payload = {'x': 'آ' * (size - len('{"x": ""}'))}
                    model.objects.filter(pk=event.pk).update(review_snapshot=payload, reason=event.reason)
                    length = model.objects.annotate(n=Length(Cast('review_snapshot', TextField()))).get(pk=event.pk).n
                    self.assertEqual(length, size)
                    response = self.client.get(reverse(route, args=[parent.pk]))
                    self.assertEqual(response.context['reviews'][0].technical_status,
                                     'invalid_record' if size == 65536 else 'oversized')
                for payload in (None, [], {'invalid': 'small-private-canary'}):
                    model.objects.filter(pk=event.pk).update(review_snapshot=Value(None, output_field=JSONField()) if payload is None else payload)
                    response = self.client.get(reverse(route, args=[parent.pk]))
                    self.assertEqual(response.context['reviews'][0].technical_status, 'invalid_record')
                    self.assertNotContains(response, 'small-private-canary')

    def test_oversized_missing_reviewer_does_not_hide_version(self):
        for domain, parent, event, model, route in self.cases():
            with self.subTest(domain=domain):
                model.objects.filter(pk=event.pk).update(reason='ر' * 1001, reviewer_id=2_147_483_000)
                try:
                    self.client.force_login(self.reviewer)
                    response = self.client.get(reverse(route, args=[parent.pk]))
                    self.assertEqual(response.context['reviews'][0].technical_status, 'oversized')
                    self.assertEqual(response.context['review_form'].initial['expected_review'], event.pk)
                    self.assertContains(response, 'بیش از حد نمایش')
                finally:
                    model.objects.filter(pk=event.pk).update(reason=event.reason, reviewer_id=self.reviewer.pk)

    def test_invalid_post_renders_bounded_history_without_writing(self):
        routes = {'source': 'staff_source_review', 'product': 'staff_product_review',
                  'price': 'staff_price_review', 'clinical': 'staff_clinical_review'}
        self.client.force_login(self.reviewer)
        for domain, parent, event, model, _ in self.cases():
            with self.subTest(domain=domain):
                model.objects.filter(pk=event.pk).update(reason='private-post-canary' + 'ر' * 100_000)
                count = model.objects.count()
                response = self.client.post(reverse(routes[domain], args=[parent.pk]), {})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(model.objects.count(), count)
                self.assertEqual(response.context['reviews'][0].technical_status, 'oversized')
                self.assertContains(response, 'بیش از حد نمایش', status_code=400)
                self.assertNotContains(response, 'private-post-canary', status_code=400)
                self.assertIn('no-store', response['Cache-Control'])
