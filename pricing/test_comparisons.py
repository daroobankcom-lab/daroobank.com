import io
import json
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from catalog.models import ProductPresentation
from .comparisons import MAX_REVISIONS, price_revision_context
from .importer import ImportValidationError, MAX_MATCH_CANDIDATES, stage_csv, suggest_product
from .models import PriceCandidate, PriceCandidateReview
from .reviews import product_fingerprint
from .test_workflow import csv_bytes


class PriceComparisonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('price-comparison-stager', password='test-only-passphrase', is_staff=True)
        cls.viewer = User.objects.create_user('price-comparison-viewer', password='test-only-passphrase', is_staff=True)
        cls.reviewer = User.objects.create_user('price-comparison-reviewer', password='test-only-passphrase', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='pricing')
        cls.stager.user_permissions.add(*perms.filter(codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.viewer.user_permissions.add(perms.get(codename='view_pricecandidate'))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_pricecandidate', 'review_pricecandidate']))
        cls.row = dict(source_record_id='synthetic-1', irc='۰۰۱۲۳۴', manufacturer='شرکت نمونه', strength='۵ mg',
                       dosage_form='قرص', package_description='۱۰ عدد', amount='12.5', currency='TOMAN',
                       category='retail', unit='package', effective_date='2026-01-01', source_published_date='')

    def stage(self, row=None, *, source='https://example.org/feed', name='منبع ساختگی'):
        row = row if row is not None else self.row
        stage_csv(io.BytesIO(csv_bytes([row])), name, source, commit=True, rights_attested=True, staged_by=self.stager)
        return PriceCandidate.objects.filter(source_url=source, source_record_id=row['source_record_id']).order_by('-pk').first()

    def product(self, *, manufacturer='شرکت نمونه'):
        return ProductPresentation.objects.create(name_fa='محصول ساختگی', manufacturer=manufacturer, strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='001234', source_name='ساختگی',
            source_url='https://example.org/product', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_exact_rial_difference_and_dates_not_a_market_trend(self):
        older = self.stage()
        row = {**self.row, 'manufacturer': 'شركت نمونه', 'irc': '001234', 'amount': '110', 'currency': 'RIAL',
               'effective_date': '', 'source_published_date': '2026-02-01'}
        current = self.stage(row)
        with self.assertNumQueries(1):
            context = price_revision_context(current)
        self.assertTrue(context['available'])
        self.assertEqual(len(context['revisions']), 1)
        item = context['revisions'][0]
        self.assertEqual(item['candidate'].pk, older.pk)
        self.assertTrue(item['comparable'])
        self.assertEqual(item['delta_rial'], -15)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_price_detail', args=[current.pk]))
        self.assertContains(response, 'تفاضل حسابی مشروط')
        self.assertContains(response, '-15')
        self.assertContains(response, '125')
        self.assertContains(response, 'تومان')
        self.assertContains(response, '2026-01-01')
        self.assertContains(response, 'نه تاریخ اثر')
        self.assertContains(response, 'اثبات یکسانی فرآورده نیست')
        self.assertContains(response, reverse('staff_price_detail', args=[older.pk]))
        self.assert_private(response)
        self.assertFalse(PriceCandidateReview.objects.exists())
        self.assertNotContains(self.client.get(reverse('prices')), '125')
        self.assertNotIn('amount_rial', str(self.client.get(reverse('search_api'), {'q': '001234'}).json()))

    def test_same_value_yields_zero_without_inventing_a_trend(self):
        self.stage()
        current = self.stage({**self.row, 'currency': 'RIAL', 'amount': '125'})
        item = price_revision_context(current)['revisions'][0]
        self.assertTrue(item['comparable'])
        self.assertEqual(item['delta_rial'], 0)
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('staff_price_detail', args=[current.pk])), 'تفاضل حسابی مشروط')

    def test_integer_difference_handles_extreme_values_without_rounding(self):
        self.stage({**self.row, 'currency': 'RIAL', 'amount': '1'})
        current = self.stage({**self.row, 'currency': 'RIAL', 'amount': '9223372036854775807'})
        item = price_revision_context(current)['revisions'][0]
        self.assertTrue(item['comparable'])
        self.assertEqual(item['delta_rial'], 9223372036854775806)

    def test_unsafe_source_fields_are_escaped_and_not_public(self):
        self.stage()
        current = self.stage({**self.row, 'manufacturer': '<script>alert(1)</script>', 'amount': '20'})
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_price_detail', args=[current.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')
        self.assertContains(response, 'تفاضل محاسبه نشد')
        self.assertEqual(self.client.get(reverse('search_api'), {'q': '001234'}).json()['data'], [])

    def test_identity_category_unit_and_source_name_differences_disable_delta(self):
        baseline = self.stage()
        variants = [
            ({**self.row, 'amount': '20', 'irc': '009999'}, 'IRC'),
            ({**self.row, 'amount': '21', 'manufacturer': 'سازنده متفاوت'}, 'سازنده'),
            ({**self.row, 'amount': '22', 'strength': '۱۰ mg'}, 'مقدار یا غلظت'),
            ({**self.row, 'amount': '23', 'dosage_form': 'کپسول'}, 'شکل دارویی'),
            ({**self.row, 'amount': '24', 'package_description': '۲۰ عدد'}, 'بسته‌بندی'),
            ({**self.row, 'amount': '25', 'category': 'wholesale'}, 'دسته قیمت'),
            ({**self.row, 'amount': '26', 'unit': 'tablet'}, 'واحد قیمت'),
        ]
        for row, expected in variants:
            with self.subTest(field=expected):
                other = self.stage(row)
                item = next(x for x in price_revision_context(other)['revisions'] if x['candidate'].pk == baseline.pk)
                self.assertFalse(item['comparable'])
                self.assertIsNone(item['delta_rial'])
                self.assertIn(expected, item['differences'])
        renamed = self.stage({**self.row, 'amount': '27'}, name='منبع متفاوت')
        item = next(x for x in price_revision_context(renamed)['revisions'] if x['candidate'].pk == baseline.pk)
        self.assertFalse(item['comparable'])
        self.assertIn('نام منبع', item['differences'])

    def test_invalid_rows_do_not_produce_arithmetic_or_echo_unsafe_data(self):
        baseline = self.stage()
        other = self.stage({**self.row, 'amount': '20'})
        PriceCandidate.objects.filter(pk=other.pk).update(amount_rial=999999)
        result = price_revision_context(baseline)
        self.assertEqual(result['revisions'][0]['candidate'].pk, other.pk)
        self.assertFalse(result['revisions'][0]['valid'])
        self.assertIsNone(result['revisions'][0]['delta_rial'])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_price_detail', args=[baseline.pk]))
        self.assertContains(response, 'داده این نسخه ناسازگار است')
        self.assertNotContains(response, '999999')
        PriceCandidate.objects.filter(pk=baseline.pk).update(source_fields={'irc': None})
        baseline.refresh_from_db()
        self.assertFalse(price_revision_context(baseline)['available'])
        response = self.client.get(reverse('staff_price_detail', args=[baseline.pk]))
        self.assertContains(response, 'مقایسه متوقف شد')

    def test_revision_cap_and_exact_source_boundaries(self):
        current = self.stage()
        for i in range(MAX_REVISIONS + 2):
            self.stage({**self.row, 'amount': str(20 + i)})
        outside = self.stage({**self.row, 'amount': '600'}, source='https://example.org/elsewhere')
        different_id = self.stage({**self.row, 'source_record_id': 'different', 'amount': '700'})
        context = price_revision_context(current)
        self.assertTrue(context['limited'])
        self.assertEqual(len(context['revisions']), MAX_REVISIONS)
        ids = [r['candidate'].pk for r in context['revisions']]
        self.assertNotIn(outside.pk, ids)
        self.assertNotIn(different_id.pk, ids)
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('staff_price_detail', args=[current.pk])), 'فقط ۱۰ نسخه اخیر')

    def test_review_filter_is_latest_and_independent_of_initial_match(self):
        one = self.stage()
        two = self.stage({**self.row, 'source_record_id': 'other'})
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('staff_prices'), {'review': 'pending', 'status': 'unmatched'})
        self.assertEqual(len(response.context['page'].object_list), 2)
        data = {'decision': 'defer', 'reason': 'به بررسی و شواهد مستقل بیشتر نیاز دارد.', 'expected_review': 0,
                'expected_product': 0, 'expected_product_hash': ''}
        self.assertEqual(self.client.post(reverse('staff_price_review', args=[one.pk]), data).status_code, 302)
        event = PriceCandidateReview.objects.get(candidate=one)
        data.update(decision='reject', expected_review=event.pk)
        self.assertEqual(self.client.post(reverse('staff_price_review', args=[one.pk]), data).status_code, 302)
        pending = self.client.get(reverse('staff_prices'), {'review': 'pending'})
        self.assertEqual([x.pk for x in pending.context['page']], [two.pk])
        rejected = self.client.get(reverse('staff_prices'), {'review': 'reject', 'status': 'unmatched'})
        self.assertEqual([x.pk for x in rejected.context['page']], [one.pk])
        self.assertEqual(len(self.client.get(reverse('staff_prices'), {'review': 'defer'}).context['page']), 0)
        self.assertContains(rejected, 'رد نامزد')
        self.assert_private(rejected)
        bad = self.client.get(reverse('staff_prices'), {'review': '<script>'})
        self.assertEqual(bad.status_code, 400)
        self.assert_private(bad)

    def test_filter_pagination_retains_both_filters(self):
        for i in range(25):
            self.stage({**self.row, 'source_record_id': f'fake-{i}'})
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_prices'), {'status': 'unmatched', 'review': 'pending'})
        self.assertEqual(len(response.context['page']), 20)
        self.assertContains(response, 'status=unmatched&amp;review=pending&amp;page=2')
        response = self.client.get(reverse('staff_prices'), {'status': 'unmatched', 'review': 'pending', 'page': 2})
        self.assertEqual(len(response.context['page']), 5)

    def test_permissions_gate_disabled_and_big_ids(self):
        candidate = self.stage()
        url = reverse('staff_price_detail', args=[candidate.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        outsider = get_user_model().objects.create_user('no-price-access', password='test-only-passphrase', is_staff=True)
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(url).status_code, 200)
        for name in ['staff_price_detail', 'staff_price_review']:
            address = reverse(name, args=[9223372036854775808])
            response = self.client.get(address) if name.endswith('detail') else self.client.post(address)
            # View-only account is denied review before looking up the id.
            self.assertEqual(response.status_code, 404 if name.endswith('detail') else 403)
            self.assert_private(response)
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse('staff_price_review', args=[9223372036854775808]))
        self.assertEqual(response.status_code, 404)
        self.assert_private(response)
        with self.settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False):
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_invisible_identity_fields_are_rejected_and_invalid_for_suggestion(self):
        for field in ['source_record_id', 'irc', 'manufacturer', 'strength', 'dosage_form', 'package_description']:
            with self.subTest(field=field), self.assertRaises(ImportValidationError):
                stage_csv(io.BytesIO(csv_bytes([{**self.row, field: '\u200d'}])), 'منبع', 'https://example.org', commit=True, rights_attested=True)
        with self.assertRaises(ImportValidationError):
            stage_csv(io.BytesIO(csv_bytes([{**self.row, 'manufacturer': 'الف\nب'}])), 'منبع', 'https://example.org', commit=True, rights_attested=True)
        with self.assertRaises(ImportValidationError):
            stage_csv(io.BytesIO(csv_bytes([self.row])), 'منبع', 'https://example.org', commit=True, rights_attested='false')
        self.assertEqual(suggest_product({'irc': None}), ('unmatched', None))
        candidate = self.stage()
        fields = {**candidate.source_fields, 'manufacturer': '\u200d'}
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields=fields)
        output = io.StringIO()
        call_command('list_price_candidates', stdout=output)
        self.assertEqual(json.loads(output.getvalue())['data'][0]['current_suggestion']['match_status'], 'invalid')
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('staff_price_detail', args=[candidate.pk])), 'اطلاعات نامعتبر')

    def test_malformed_unicode_in_json_fails_closed_without_breaking_staff_pages(self):
        candidate = self.stage()
        self.client.force_login(self.viewer)
        for field in ['irc', 'manufacturer', 'strength', 'dosage_form', 'package_description']:
            with self.subTest(field=field):
                fields = {**candidate.source_fields, field: '\u0001'}
                PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields=fields)
                damaged = PriceCandidate.objects.get(pk=candidate.pk)
                self.assertFalse(price_revision_context(damaged)['available'])
                for url in [reverse('staff_prices'), reverse('staff_price_detail', args=[candidate.pk])]:
                    response = self.client.get(url)
                    self.assertEqual(response.status_code, 200)
                    self.assert_private(response)
                self.assertContains(self.client.get(reverse('staff_price_detail', args=[candidate.pk])), 'مقایسه متوقف شد')

    def test_review_rechecks_overflow_after_form_was_loaded(self):
        product = self.product()
        candidate = self.stage()
        self.assertEqual(candidate.match_status, 'suggested')
        self.client.force_login(self.reviewer)
        detail = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertEqual(detail.context['current_product'], product)
        for _ in range(MAX_MATCH_CANDIDATES):
            self.product(manufacturer='سازنده متفاوت')
        response = self.client.post(reverse('staff_price_review', args=[candidate.pk]), {
            'decision': 'accept_suggestion', 'reason': 'بررسی نمونه با تأیید دوباره تطبیق.',
            'expected_review': 0, 'expected_product': product.pk,
            'expected_product_hash': product_fingerprint(product),
        })
        self.assertEqual(response.status_code, 409)
        self.assertFalse(PriceCandidateReview.objects.exists())
        self.assertContains(response, 'پیشنهاد تطبیق فعلی یکتا نیست', status_code=409)

    def test_match_candidate_limit_is_conservative(self):
        expected = self.product()
        for _ in range(MAX_MATCH_CANDIDATES - 1):
            self.product(manufacturer='سازنده متفاوت')
        self.assertEqual(suggest_product(self.row), ('suggested', expected))
        self.product(manufacturer='سازنده متفاوت')
        self.assertEqual(suggest_product(self.row), ('ambiguous', None))
        no_match = {**self.row, 'manufacturer': 'هیچ‌کدام'}
        self.assertEqual(suggest_product(no_match), ('ambiguous', None))
        self.assertEqual(self.stage().match_status, 'ambiguous')
