import importlib
import io
from datetime import datetime, timezone
from types import SimpleNamespace

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from .comparisons import MAX_COMPARISONS, product_comparison_context
from .intake import fingerprint, stage_products
from .models import ProductCandidate, ProductCandidateReview, ProductPresentation
from .test_intake import make_csv


class ProductComparisonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('comparison-stager', password='test-only-passphrase', is_staff=True)
        cls.viewer = User.objects.create_user('comparison-viewer', password='test-only-passphrase', is_staff=True)
        cls.reviewer = User.objects.create_user('comparison-reviewer', password='test-only-passphrase', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='catalog')
        cls.stager.user_permissions.add(*perms.filter(codename__in=['view_productcandidate', 'add_productcandidate']))
        cls.viewer.user_permissions.add(perms.get(codename='view_productcandidate'))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_productcandidate', 'review_productcandidate']))
        cls.row = {'source_record_id': 'synthetic', 'name_fa': 'نمونه فرضی', 'name_en': 'Example',
                   'manufacturer': 'شرکت فرضی', 'strength': '۵ mg', 'dosage_form': 'قرص',
                   'package_description': '۱۰ عدد', 'irc': '۰۰۱۲۳۴'}

    def stage(self, row=None, source_url='https://example.org/source', source_name='منبع فرضی'):
        row = self.row if row is None else row
        stage_products(io.BytesIO(make_csv([row])), source_name, source_url, actor=self.stager, commit=True, rights_attested=True)
        return ProductCandidate.objects.get(source_url=source_url, source_record_id=row['source_record_id'],
                                            payload_sha256=fingerprint(source_name, source_url, row))

    def product(self, *, name='محصول منتشرشده', published=True, irc='001234', **kwargs):
        values = dict(name_fa=name, manufacturer='شركت فرضی', strength='5 mg', dosage_form='قرص',
                      package_description='20 عدد', irc=irc, source_name='منبع ساختگی',
                      source_url='https://example.org/product', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      published=published)
        values.update(kwargs)
        return ProductPresentation.objects.create(**values)

    def test_revision_and_normalized_irc_comparison_is_advisory(self):
        older = self.stage()
        newer = self.stage({**self.row, 'strength': '۱۰ mg', 'manufacturer': 'شركت فرضی'}, source_name='منبع دیگر')
        other = self.stage({**self.row, 'source_record_id': 'other-1', 'name_fa': '<b>نام دیگر</b>', 'irc': '001234'},
                           source_url='https://example.org/other')
        public = self.product()
        self.product(name='داده خصوصی کاتالوگ', published=False)
        self.client.force_login(self.viewer)
        with self.assertNumQueries(3):
            context = product_comparison_context(newer)
        self.assertTrue(context['available'])
        self.assertTrue(context['has_irc'])
        self.assertEqual(newer.irc_normalized, '001234')
        self.assertEqual([x['candidate'].pk for x in context['revisions']], [older.pk])
        self.assertTrue(context['revisions'][0]['source_name_changed'])
        revision_changes = context['revisions'][0]['changes']
        self.assertTrue(any(c['label'] == 'سازنده' and c['normalized_equal'] for c in revision_changes))
        self.assertTrue(any(c['label'] == 'مقدار یا غلظت' and not c['normalized_equal'] for c in revision_changes))
        self.assertEqual({x['candidate'].pk for x in context['candidate_matches']}, {older.pk, other.pk})
        self.assertEqual([x['product'].pk for x in context['public_matches']], [public.pk])
        response = self.client.get(reverse('staff_product_detail', args=[newer.pk]))
        self.assertContains(response, 'سرنخ‌های مقایسه و تغییرات')
        self.assertContains(response, 'نه اثبات معادل بودن')
        self.assertContains(response, 'این مقایسه‌ها هویت')
        self.assertContains(response, '&lt;b&gt;نام دیگر&lt;/b&gt;')
        self.assertNotContains(response, '<b>نام دیگر</b>')
        self.assertNotContains(response, 'داده خصوصی کاتالوگ')
        self.assertContains(response, reverse('presentation_detail', args=[public.pk]))
        self.assertContains(response, 'پیش‌نویس‌های کاتالوگ در این مقایسه نیستند')
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(ProductCandidateReview.objects.count(), 0)
        self.assertEqual(ProductPresentation.objects.count(), 2)

    def test_missing_irc_and_invalid_candidate_never_imply_no_conflict(self):
        candidate = self.stage({**self.row, 'irc': ''})
        self.assertEqual(candidate.irc_normalized, '')
        ctx = product_comparison_context(candidate)
        self.assertTrue(ctx['available'])
        self.assertFalse(ctx['has_irc'])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertContains(response, 'مقایسه بر اساس کد انجام نشد')
        candidate.irc_normalized = 'wrong'
        candidate.save(update_fields=['irc_normalized'])
        self.assertFalse(product_comparison_context(candidate)['available'])
        self.assertContains(self.client.get(reverse('staff_product_detail', args=[candidate.pk])), 'مقایسه متوقف شد')
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse('staff_product_review', args=[candidate.pk]), {
            'decision': 'defer', 'reason': 'نیازمند بررسی بیشتر و شواهد مستقل است.',
            'expected_hash': candidate.payload_sha256, 'expected_review': 0,
        })
        self.assertEqual(response.status_code, 409)
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_corrupted_and_stale_index_records_are_not_displayed(self):
        candidate = self.stage()
        other = self.stage({**self.row, 'source_record_id': 'other', 'name_fa': 'محرمانه نامعتبر'})
        ProductCandidate.objects.filter(pk=other.pk).update(source_fields={**other.source_fields, 'irc': '999'})
        good = self.product()
        stale = self.product(name='نمایه خراب')
        ProductPresentation.objects.filter(pk=stale.pk).update(irc='999')
        unsafe = self.product(name='منبع خراب')
        ProductPresentation.objects.filter(pk=unsafe.pk).update(source_url='https://user:secret@example.org')
        context = product_comparison_context(candidate)
        self.assertEqual(context['candidate_matches'], [])
        self.assertEqual(context['candidate_skipped'], 1)
        self.assertEqual([x['product'].pk for x in context['public_matches']], [good.pk])
        self.assertEqual(context['public_skipped'], 2)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertContains(response, 'برخی نامزدهای بررسی‌شده')
        self.assertContains(response, 'برخی رکوردهای بررسی‌شده')
        self.assertNotContains(response, 'محرمانه نامعتبر')
        self.assertNotContains(response, 'نمایه خراب')
        self.assertNotContains(response, 'منبع خراب')

    def test_caps_and_no_uniqueness_assumption(self):
        candidate = self.stage()
        for i in range(MAX_COMPARISONS + 1):
            self.stage({**self.row, 'strength': f'{i} mg'})
            self.stage({**self.row, 'source_record_id': f'other-{i}'})
            self.product(name=f'محصول فرضی {i}')
        context = product_comparison_context(candidate)
        self.assertEqual(len(context['revisions']), MAX_COMPARISONS)
        self.assertEqual(len(context['candidate_matches']), MAX_COMPARISONS)
        self.assertEqual(len(context['public_matches']), MAX_COMPARISONS)
        self.assertTrue(context['revisions_limited'])
        self.assertTrue(context['candidate_matches_limited'])
        self.assertTrue(context['public_matches_limited'])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertContains(response, 'فقط ۱۰ مورد')
        self.assertContains(response, 'نبود نتیجه نشان‌دهنده یکتایی یا نبود تعارض نیست')

    def test_migration_backfill_handles_old_and_invalid_rows_without_truncating(self):
        valid = self.stage()
        bad = self.stage({**self.row, 'source_record_id': 'bad'})
        oversized = self.stage({**self.row, 'source_record_id': 'over'})
        ProductCandidate.objects.filter(pk=valid.pk).update(irc_normalized='')
        ProductCandidate.objects.filter(pk=bad.pk).update(source_fields={'irc': None}, irc_normalized='stale')
        ProductCandidate.objects.filter(pk=oversized.pk).update(source_fields={'irc': 'ﬃ' * 40}, irc_normalized='stale')
        migration = importlib.import_module('catalog.migrations.0004_productcandidate_irc_normalized')
        migration.backfill_candidate_irc(apps, SimpleNamespace(connection=connection))
        valid.refresh_from_db(); bad.refresh_from_db(); oversized.refresh_from_db()
        self.assertEqual(valid.irc_normalized, '001234')
        self.assertEqual(bad.irc_normalized, '')
        self.assertEqual(oversized.irc_normalized, '')

    def test_staff_gate_and_non_public_access(self):
        candidate = self.stage()
        url = reverse('staff_product_detail', args=[candidate.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('presentation_api', args=[candidate.pk])).status_code, 404)
