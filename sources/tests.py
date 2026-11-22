import io
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.intake import stage_products
from catalog.models import ProductCandidate, ProductPresentation
from catalog.test_intake import make_csv
from pricing.importer import stage_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from .models import SourceClaim, SourceClaimReview
from .services import ClaimError, ReviewConflict, date_label, record_claim, related_claims, review_claim, valid_claim


class SourceClaimTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('source-author', password='test-only-password', is_staff=True)
        cls.reviewer = User.objects.create_user('source-reviewer', password='test-only-password', is_staff=True)
        cls.viewer = User.objects.create_user('source-viewer', password='test-only-password', is_staff=True)
        cls.add_only = User.objects.create_user('source-add-only', password='test-only-password', is_staff=True)
        cls.regular = User.objects.create_user('source-regular', password='test-only-password')
        perms = Permission.objects.filter(content_type__app_label='sources')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_sourceclaim', 'add_sourceclaim', 'review_sourceclaim']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_sourceclaim', 'review_sourceclaim']))
        cls.viewer.user_permissions.add(perms.get(codename='view_sourceclaim'))
        cls.add_only.user_permissions.add(perms.get(codename='add_sourceclaim'))
        cls.regular.user_permissions.add(perms.get(codename='view_sourceclaim'))
        cls.data = dict(source_name='منبع ساختگی', source_url='https://example.org/feed', owner='مالک فرضی',
                        evidence_url='https://example.org/evidence', evidence_note='ارجاع ساختگی',
                        claims_collection=True, claims_storage=True, claims_publication=False,
                        starts_on=date(2026, 1, 1), expires_on=date(2026, 12, 31))

    def post_data(self, **changes):
        data = {**self.data, **changes}
        return {**data, 'starts_on': data['starts_on'].isoformat() if data['starts_on'] else '',
                'expires_on': data['expires_on'].isoformat() if data['expires_on'] else '',
                'attestation': 'on', 'claims_collection': 'on' if data['claims_collection'] else '',
                'claims_storage': 'on' if data['claims_storage'] else '',
                'claims_publication': 'on' if data['claims_publication'] else ''}

    def claim(self, **changes):
        claim, created = record_claim(actor=self.author, data={**self.data, **changes})
        self.assertTrue(created)
        return claim

    def review_data(self, claim, decision='further_review', expected_review=0):
        return {'decision': decision, 'reason': 'این مدرک ساختگی به بررسی بیشتر نیاز دارد.',
                'expected_review': expected_review, 'expected_hash': claim.payload_sha256}

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')

    def test_staff_permissions_group_and_login_redirect(self):
        for name in ['staff_sources', 'staff_source_create']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302)
            self.assert_private(r)
        for user in [self.regular, self.add_only]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('staff_sources')).status_code, 403)
            self.assertEqual(self.client.get(reverse('staff_source_create')).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('staff_sources')).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff_source_create')).status_code, 403)
        group = Group.objects.create(name='synthetic-source-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='sources', codename='view_sourceclaim'))
        user = get_user_model().objects.create_user('source-group', password='test-only-password', is_staff=True)
        user.groups.add(group)
        self.client.logout()
        self.assertRedirects(self.client.post(reverse('staff_login'), {'username': 'source-group', 'password': 'test-only-password'}), reverse('staff_sources'))

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_portal_for_all_actions(self):
        self.client.force_login(self.author)
        for name, args in [('staff_sources', []), ('staff_source_create', []), ('staff_source_detail', [1]), ('staff_source_review', [1])]:
            for method in [self.client.get, self.client.post]:
                response = method(reverse(name, args=args))
                self.assertEqual(response.status_code, 404)
                self.assert_private(response)

    def test_validation_attestation_dedup_and_versions(self):
        self.client.force_login(self.author)
        data = self.post_data(); data.pop('attestation')
        self.assertEqual(self.client.post(reverse('staff_source_create'), data).status_code, 200)
        self.assertEqual(SourceClaim.objects.count(), 0)
        response = self.client.post(reverse('staff_source_create'), self.post_data())
        self.assertEqual(response.status_code, 302)
        claim = SourceClaim.objects.get()
        self.assertEqual(claim.recorded_by, self.author)
        other = get_user_model().objects.create_user('source-other', password='test-only-password', is_staff=True)
        other.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources', codename__in=['view_sourceclaim', 'add_sourceclaim', 'review_sourceclaim']))
        self.client.force_login(other)
        self.assertRedirects(self.client.post(reverse('staff_source_create'), self.post_data()), reverse('staff_source_detail', args=[claim.pk]))
        claim.refresh_from_db(); self.assertEqual(claim.recorded_by, self.author)
        self.assertEqual(self.client.post(reverse('staff_source_create'), self.post_data(owner='مالک دیگر')).status_code, 302)
        self.assertEqual(SourceClaim.objects.count(), 2)
        self.assertEqual(ProductPresentation.objects.count(), 0)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        with self.assertRaises(ValidationError): claim.save()
        with self.assertRaises(ValidationError): claim.delete()

    def test_input_validation_and_services_do_not_fetch_any_url(self):
        with patch('socket.create_connection', side_effect=AssertionError('network access forbidden')):
            self.claim()
        for changes in [dict(source_url='http://example.org'), dict(evidence_url='javascript:alert(1)'),
                        dict(source_url='https://user:secret@example.org'), dict(evidence_url='https://example.org/?token=secret'),
                        dict(source_url='https://example.org/#fragment'), dict(source_url='https://example.org/?'),
                        dict(evidence_url='https://example.org/#'), dict(source_url='https://example.org/\ud800'), dict(owner='\u200d'), dict(evidence_note='hello\nworld'),
                        dict(claims_collection=False, claims_storage=False, claims_publication=False),
                        dict(starts_on=date(2027, 1, 1), expires_on=date(2026, 1, 1)), dict(claims_collection='true')]:
            with self.subTest(changes=changes), self.assertRaises(ClaimError):
                record_claim(actor=self.author, data={**self.data, **changes})
        self.assertEqual(SourceClaim.objects.count(), 1)
        for actor in [self.viewer, self.add_only, self.regular, self.reviewer]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                record_claim(actor=actor, data=self.data)

    def test_date_comparison_uses_tehran_today_and_unknown_is_not_permission(self):
        within = self.claim()
        unknown = self.claim(owner='نام دوم', starts_on=None)
        future = self.claim(owner='نام سوم', starts_on=date(2027, 1, 1), expires_on=None)
        expired = self.claim(owner='نام چهارم', starts_on=None, expires_on=date(2025, 1, 1))
        with patch('sources.services.timezone.localdate', return_value=date(2026, 1, 1)):
            self.assertEqual(date_label(within), 'within_dates')
            self.assertEqual(date_label(unknown), 'unknown')
            self.assertEqual(date_label(future), 'future')
            self.assertEqual(date_label(expired), 'expired')
        with patch('sources.services.timezone.localdate', return_value=date(2026, 12, 31)):
            self.assertEqual(date_label(within), 'within_dates')
        with patch('sources.services.timezone.localdate', return_value=date(2027, 1, 1)):
            self.assertEqual(date_label(within), 'expired')
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_source_detail', args=[within.pk]))
        self.assertContains(response, 'به معنی اعتبار مجوز یا راستی‌آزمایی مدرک نیست')
        self.assertNotContains(response, 'href="https://example.org/evidence"')

    def test_review_separation_versions_and_tampering(self):
        claim = self.claim()
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(reverse('staff_source_review', args=[claim.pk]), self.review_data(claim)).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('staff_source_review', args=[claim.pk]), self.review_data(claim)).status_code, 403)
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('staff_source_detail', args=[claim.pk]))
        self.assertContains(response, 'ثبت بازبینی اولیه')
        self.assert_private(response)
        self.assertEqual(self.client.post(reverse('staff_source_review', args=[claim.pk]), self.review_data(claim)).status_code, 302)
        event = SourceClaimReview.objects.get()
        self.assertEqual(event.reviewer, self.reviewer)
        self.assertEqual(event.review_snapshot['source_url'], claim.source_url)
        self.assertEqual(event.review_snapshot['recorded_by_id'], self.author.pk)
        self.assertEqual(event.review_snapshot['expires_on'], '2026-12-31')
        self.assertEqual(self.client.post(reverse('staff_source_review', args=[claim.pk]), self.review_data(claim)).status_code, 409)
        with self.assertRaises(ReviewConflict):
            review_claim(actor=self.reviewer, claim_id=claim.pk, **{**self.review_data(claim), 'expected_hash': '0' * 64})
        with self.assertRaises(ReviewConflict):
            review_claim(actor=self.reviewer, claim_id=claim.pk, **{**self.review_data(claim), 'reason': 'یک متن ساختگی کافی \ud800'})
        data = self.review_data(claim, 'defer', event.pk)
        self.assertEqual(self.client.post(reverse('staff_source_review', args=[claim.pk]), data).status_code, 302)
        self.assertEqual(SourceClaimReview.objects.count(), 2)
        with self.assertRaises(ValidationError): event.save()
        with self.assertRaises(ValidationError): event.delete()
        claim.owner = '\ud800'
        self.assertFalse(valid_claim(claim))
        claim.refresh_from_db()
        SourceClaim.objects.filter(pk=claim.pk).update(owner='تغییر غیرمجاز')
        result = self.client.get(reverse('staff_source_detail', args=[claim.pk]))
        self.assertContains(result, 'داده ناسازگار است')
        self.assertEqual(self.client.post(reverse('staff_source_review', args=[claim.pk]), data).status_code, 409)
        self.assertEqual(SourceClaimReview.objects.count(), 2)

    def test_csrf_actual_flow_and_escaped_values(self):
        stager = Client(enforce_csrf_checks=True)
        stager.force_login(self.author)
        url = reverse('staff_source_create')
        self.assertEqual(stager.post(url, self.post_data()).status_code, 403)
        stager.get(url)
        data = self.post_data(source_name='<script>alert(1)</script>'); data['csrfmiddlewaretoken'] = stager.cookies['csrftoken'].value
        self.assertEqual(stager.post(url, data).status_code, 302)
        claim = SourceClaim.objects.get()
        reviewer = Client(enforce_csrf_checks=True); reviewer.force_login(self.reviewer)
        url = reverse('staff_source_review', args=[claim.pk])
        self.assertEqual(reviewer.post(url, self.review_data(claim)).status_code, 403)
        detail = reviewer.get(reverse('staff_source_detail', args=[claim.pk]))
        self.assertNotContains(detail, '<script>alert(1)</script>')
        self.assertContains(detail, '&lt;script&gt;')
        data = self.review_data(claim); data['csrfmiddlewaretoken'] = reviewer.cookies['csrftoken'].value
        self.assertEqual(reviewer.post(url, data).status_code, 302)
        self.assertEqual(SourceClaimReview.objects.count(), 1)
        self.assertEqual(reviewer.get(url).status_code, 405)

    def test_filter_pagination_and_invalid_id(self):
        for i in range(25): self.claim(owner=f'مالک فرضی {i}')
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_sources'), {'status': 'pending'})
        self.assertEqual(len(response.context['page']), 20)
        self.assertContains(response, 'status=pending&amp;page=2')
        self.assertEqual(len(self.client.get(reverse('staff_sources'), {'status': 'pending', 'page': 2}).context['page']), 5)
        response = self.client.get(reverse('staff_sources'), {'status': '<script>'})
        self.assertEqual(response.status_code, 400); self.assert_private(response)
        response = self.client.get(reverse('staff_source_detail', args=[9223372036854775808]))
        self.assertEqual(response.status_code, 404); self.assert_private(response)

    def test_latest_review_filter(self):
        claim = self.claim(); other = self.claim(owner='مالک دیگر')
        event = review_claim(actor=self.reviewer, claim_id=claim.pk, **self.review_data(claim, 'defer'))
        review_claim(actor=self.reviewer, claim_id=claim.pk, **self.review_data(claim, 'reject', event.pk))
        self.client.force_login(self.viewer)
        self.assertEqual([c.pk for c in self.client.get(reverse('staff_sources'), {'status': 'pending'}).context['page']], [other.pk])
        self.assertEqual([c.pk for c in self.client.get(reverse('staff_sources'), {'status': 'reject'}).context['page']], [claim.pk])
        self.assertEqual(len(self.client.get(reverse('staff_sources'), {'status': 'defer'}).context['page']), 0)

    def test_related_claims_are_exact_bounded_and_permission_gated(self):
        for i in range(7): self.claim(owner=f'مالک ساختگی {i}')
        self.claim(owner='منبع دیگر', source_url='https://example.org/other')
        self.assertFalse(self.add_only.has_perm('sources.view_sourceclaim'))  # warm Django's permission cache
        with self.assertNumQueries(0):
            self.assertEqual(related_claims(self.add_only, self.data['source_url']), {'can_view': False})
        summary = related_claims(self.viewer, self.data['source_url'])
        self.assertEqual(len(summary['items']), 5)
        self.assertTrue(summary['limited'])
        self.assertTrue(all(item['claim'].source_url == self.data['source_url'] for item in summary['items']))
        self.assertTrue(related_claims(self.viewer, 'https://example.org/?secret=token')['invalid_url'])

    def test_product_and_price_details_show_claims_only_with_separate_permission(self):
        claim = self.claim()
        self.author.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog', codename__in=['view_productcandidate', 'add_productcandidate']))
        self.author.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing', codename__in=['view_pricecandidate', 'add_pricecandidate']))
        self.author = get_user_model().objects.get(pk=self.author.pk)  # clear permission cache
        product_row = dict(source_record_id='p-synthetic', name_fa='فرآورده ساختگی', name_en='', manufacturer='سازنده فرضی', strength='۵ mg', dosage_form='قرص', package_description='۱۰ عدد', irc='001234')
        price_row = dict(source_record_id='price-synthetic', irc='001234', manufacturer='سازنده فرضی', strength='۵ mg', dosage_form='قرص', package_description='۱۰ عدد', amount='100', currency='RIAL', category='retail', unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([product_row])), 'نمونه', claim.source_url, actor=self.author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([price_row])), 'نمونه', claim.source_url, staged_by=self.author, commit=True, rights_attested=True)
        product = ProductCandidate.objects.get(); price = PriceCandidate.objects.get()
        self.client.force_login(self.author)
        for url in [reverse('staff_product_detail', args=[product.pk]), reverse('staff_price_detail', args=[price.pk])]:
            response = self.client.get(url)
            self.assertContains(response, reverse('staff_source_detail', args=[claim.pk]))
            self.assertContains(response, 'این فهرست کنترل یا مجاز نمی‌شود')
        limited = get_user_model().objects.create_user('no-source-view', password='test-only-password', is_staff=True)
        limited.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog', codename='view_productcandidate'))
        limited.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing', codename='view_pricecandidate'))
        self.client.force_login(limited)
        for url in [reverse('staff_product_detail', args=[product.pk]), reverse('staff_price_detail', args=[price.pk])]:
            response = self.client.get(url)
            self.assertContains(response, 'برای مشاهده ادعاهای منبع به مجوز جداگانه نیاز است')
            self.assertNotContains(response, reverse('staff_source_detail', args=[claim.pk]))
            self.assertNotContains(response, 'مالک فرضی')
        self.assertEqual(ProductPresentation.objects.count(), 0)
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/')
        self.assertEqual(self.client.get(reverse('search_api'), {'q': '001234'}).json()['data'], [])
