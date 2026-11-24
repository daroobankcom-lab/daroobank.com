"""Synthetic content transfer bounds for source and clinical review scans."""
from unittest.mock import patch

from django.db import connection
from django.db.models import JSONField, TextField, Value
from django.db.models.functions import Cast, Length
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from clinical import review_inspection as clinical_scan
from sources import review_inspection as source_scan
from . import test_recent_review_bounded_content as fixtures


@override_settings(STAFF_PORTAL_ENABLED=True)
class OtherReviewScanBoundedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RecentReviewBoundedContentTests.setUpTestData.__func__(cls)

    def cases(self):
        return [(source_scan, self.claim, self.source_event, 'claim_id', 'staff_source_review_inspection'),
                (clinical_scan, self.draft, self.clinical_event, 'draft_id', 'staff_clinical_review_inspection')]

    def scan(self, module, parent, key, **kwargs):
        return module.inspect_reviews(actor=self.viewer, **{key: parent.pk}, **kwargs)

    def test_oversized_payload_and_reason_not_transferred_or_classified(self):
        self.client.force_login(self.viewer)
        for module, parent, event, key, route in self.cases():
            with self.subTest(domain=key):
                model = type(event)
                model.objects.filter(pk=event.pk).update(review_snapshot={'private-canary': 'آ' * 1_000_000},
                    reason='ر' * 100_000 + 'reason-canary')
                with patch.object(module, 'classify_review', side_effect=AssertionError('partial review classified')):
                    with CaptureQueriesContext(connection) as queries:
                        report = self.scan(module, parent, key)
                self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'oversized', 'comparison': 'unknown'}])
                query = next(q['sql'] for q in queries if f'FROM "{model._meta.db_table}"' in q['sql'])
                select = query.split(' FROM ', 1)[0].lower()
                self.assertIn('case', select)
                self.assertIn('substring', select)
                self.assertNotRegex(select, rf'(?:^select |, )"{model._meta.db_table}"\."(?:reason|review_snapshot)"(?:,|$)')
                self.assertIn('LIMIT 51', query)
                response = self.client.get(reverse(route, args=[parent.pk]), {'category': 'oversized'})
                self.assertContains(response, 'بیش از حد بازرسی')
                self.assertNotContains(response, 'private-canary')
                self.assertNotContains(response, 'reason-canary')
                self.assertIn('no-store', response['Cache-Control'])
                event.refresh_from_db()
                self.assertEqual(len(event.review_snapshot['private-canary']), 1_000_000)

    def test_limits_and_malformed_json(self):
        for module, parent, event, key, _ in self.cases():
            with self.subTest(domain=key):
                model = type(event)
                for length in (1000, 1001):
                    model.objects.filter(pk=event.pk).update(review_snapshot=event.review_snapshot, reason='ر' * length)
                    self.assertEqual(self.scan(module, parent, key)['rows'][0]['status'],
                                     'consistent' if length == 1000 else 'oversized')
                for length in (65536, 65537):
                    model.objects.filter(pk=event.pk).update(reason=event.reason,
                        review_snapshot={'x': 'آ' * (length - len('{"x": ""}'))})
                    self.assertEqual(model.objects.annotate(n=Length(Cast('review_snapshot', TextField()))).get(pk=event.pk).n, length)
                    self.assertEqual(self.scan(module, parent, key)['rows'][0]['status'],
                                     'invalid_record' if length == 65536 else 'oversized')
                for payload in (Value(None, output_field=JSONField()), [], {'bad': 'private-canary'}):
                    model.objects.filter(pk=event.pk).update(review_snapshot=payload)
                    self.assertEqual(self.scan(module, parent, key)['rows'][0]['status'], 'invalid_record')

    def test_large_sentinel_and_filtered_continuation(self):
        for module, parent, event, key, _ in self.cases():
            with self.subTest(domain=key):
                model = type(event)
                values = {field.attname: getattr(event, field.attname) for field in model._meta.concrete_fields
                          if field.name not in ('id', 'created_at')}
                model.objects.bulk_create([model(**values) for _ in range(49)])
                sentinel = model.objects.create(**{**values, 'review_snapshot': {'private-canary': 'آ' * 1_000_000}})
                first = self.scan(module, parent, key, category='oversized')
                self.assertEqual(first['scanned'], 50)
                self.assertEqual(first['rows'], [])
                self.assertEqual(first['next_after'], model.objects.filter(pk__lt=sentinel.pk).order_by('-pk').first().pk)
                next_page = self.scan(module, parent, key, category='oversized', after=first['next_after'])
                self.assertEqual(next_page['rows'], [{'id': sentinel.pk, 'status': 'oversized', 'comparison': 'unknown'}])
                self.assertIsNone(next_page['next_after'])
