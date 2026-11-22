from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from pricing.models import PriceCandidate
from sources.services import record_claim
from .models import ClinicalDraft, ClinicalDraftReview
from .evidence import evidence_state
from .services import DraftConflict, DraftError, create_draft, draft_data, fingerprint, review_draft, valid_draft, valid_payload


class ClinicalWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.author = U.objects.create_user('clinical-author', password='test-only-password', is_staff=True)
        cls.reviewer = U.objects.create_user('clinical-reviewer', password='test-only-password', is_staff=True)
        cls.viewer = U.objects.create_user('clinical-viewer', password='test-only-password', is_staff=True)
        cls.add_only = U.objects.create_user('clinical-add-only', password='test-only-password', is_staff=True)
        cls.regular = U.objects.create_user('clinical-regular', password='test-only-password')
        cls.inactive = U.objects.create_user('clinical-inactive', password='test-only-password', is_staff=True, is_active=False)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        cls.viewer.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.add_only.user_permissions.add(perms.get(codename='add_clinicaldraft'))
        cls.regular.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.inactive.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.data = {'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
                    'statement': 'این متن کاملاً ساختگی و صرفاً برای آزمون است.',
                    'reference_title': 'ارجاع ساختگی', 'reference_url': 'https://example.org/reference',
                    'reference_location': 'بخش ساختگی ۱', 'reference_author': 'نویسنده فرضی', 'reference_version': 'نسخه صفر',
                    'reference_published_on': date(2025, 1, 1), 'reference_accessed_on': None}

    def create(self, **changes):
        return create_draft(actor=self.author, data={**self.data, **changes})

    def form_data(self, data=None):
        data = dict(data or self.data)
        for key in ('reference_published_on', 'reference_accessed_on'):
            data[key] = data[key].isoformat() if data[key] else ''
        return {**data, 'synthetic_ack': 'on'}

    def review_data(self, draft, decision='further_review', expected_review=0):
        return {'decision': decision, 'reason': 'این مورد ساختگی به بررسی بیشتری نیاز دارد.',
                'expected_review': expected_review, 'expected_hash': draft.payload_sha256,
                'expected_evidence_hash': evidence_state(draft)['fingerprint']}

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control']); self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_access_permissions_group_and_clinical_only_login(self):
        for name, args in [('staff_clinical_drafts', []), ('staff_clinical_create', []),
                           ('staff_clinical_detail', [1]), ('staff_clinical_revise', [1]), ('staff_clinical_review', [1])]:
            response = self.client.get(reverse(name, args=args)); self.assertEqual(response.status_code, 302); self.assert_private(response)
        for user in [self.add_only, self.regular]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('staff_clinical_drafts')).status_code, 403)
            self.assertEqual(self.client.get(reverse('staff_clinical_create')).status_code, 403)
        self.client.force_login(self.inactive)
        self.assertEqual(self.client.get(reverse('staff_clinical_drafts')).status_code, 302)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('staff_clinical_drafts')).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff_clinical_create')).status_code, 403)
        group = Group.objects.create(name='clinical-synthetic-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='view_clinicaldraft'))
        user = get_user_model().objects.create_user('clinical-group', password='test-only-password', is_staff=True); user.groups.add(group)
        self.client.logout()
        self.assertRedirects(self.client.post(reverse('staff_login'), {'username': user.username, 'password': 'test-only-password'}), reverse('staff_clinical_drafts'))

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_all_endpoints_disabled_without_debug_portal(self):
        self.client.force_login(self.author)
        for name, args in [('staff_clinical_drafts', []), ('staff_clinical_create', []), ('staff_clinical_detail', [1]),
                           ('staff_clinical_revise', [1]), ('staff_clinical_review', [1])]:
            for method in [self.client.get, self.client.post]:
                response = method(reverse(name, args=args)); self.assertEqual(response.status_code, 404); self.assert_private(response)

    def test_form_ack_validation_and_no_publication(self):
        self.client.force_login(self.author)
        data = self.form_data(); data.pop('synthetic_ack')
        self.assertEqual(self.client.post(reverse('staff_clinical_create'), data).status_code, 200)
        self.assertEqual(ClinicalDraft.objects.count(), 0)
        data = self.form_data(); data['reference_published_on'] = '2026-02-30'
        self.assertEqual(self.client.post(reverse('staff_clinical_create'), data).status_code, 200)
        self.assertEqual(ClinicalDraft.objects.count(), 0)
        response = self.client.post(reverse('staff_clinical_create'), self.form_data())
        draft = ClinicalDraft.objects.get()
        self.assertRedirects(response, reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertEqual(draft.author, self.author); self.assertIsNone(draft.parent_id)
        self.assertEqual(draft.reference_published_on, date(2025, 1, 1)); self.assertIsNone(draft.reference_accessed_on)
        self.assertEqual(PriceCandidate.objects.count(), 0); self.assertEqual(ProductPresentation.objects.count(), 0)
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/')
        self.assertNotContains(self.client.get(reverse('home')), self.data['statement'])
        self.assertEqual(self.client.get(reverse('search_api'), {'q': self.data['subject']}).json()['data'], [])
        detail = self.client.get(reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertNotContains(detail, 'href="https://example.org/reference"')
        self.assertContains(detail, 'هیچ محتوایی منتشر نمی‌شود')
        self.assert_private(detail)

    def test_service_validation_no_network_and_permission_boundaries(self):
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            self.create()
        for user in [self.viewer, self.reviewer, self.add_only, self.regular, self.inactive, None]:
            with self.subTest(user=user), self.assertRaises(PermissionDenied):
                create_draft(actor=user, data=self.data)
        for changes in [dict(subject='\u200d'), dict(audience='other'), dict(audience=[]), dict(title=''),
                        dict(statement='\ud800'), dict(statement='abc\x00def'), dict(reference_location=''),
                        dict(reference_url='http://example.org'), dict(reference_url='https://a:b@example.org'),
                        dict(reference_url='https://example.org/?'), dict(reference_url='https://example.org/#'),
                        dict(reference_published_on='2026-01-01')]:
            with self.subTest(changes=ascii(changes)), self.assertRaises(DraftError):
                create_draft(actor=self.author, data={**self.data, **changes})
        self.assertEqual(ClinicalDraft.objects.count(), 1)

    def test_independent_review_snapshot_and_stale_conflicts(self):
        draft = self.create()
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft)).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft)).status_code, 403)
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertContains(response, 'ثبت بازبینی اولیه')
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft)).status_code, 302)
        review = ClinicalDraftReview.objects.get()
        self.assertEqual(review.reviewer, self.reviewer); self.assertEqual(review.draft_payload_sha256, draft.payload_sha256)
        self.assertEqual(review.review_snapshot['author_id'], self.author.pk)
        self.assertEqual(review.review_snapshot['reference_published_on'], '2025-01-01')
        self.assertIsNone(review.review_snapshot['reference_accessed_on'])
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft)).status_code, 409)
        data = self.review_data(draft, 'defer', review.pk)
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), data).status_code, 302)
        self.assertEqual(ClinicalDraftReview.objects.count(), 2)
        self.assertNotIn('approve', dict(ClinicalDraftReview.DECISIONS))
        with self.assertRaises(DraftConflict):
            review_draft(actor=self.reviewer, draft_id=9223372036854775808, **self.review_data(draft))
        with self.assertRaises(DraftConflict):
            review_draft(actor=self.reviewer, draft_id=draft.pk, **{**self.review_data(draft), 'expected_hash': '0' * 64})
        with self.assertRaises(DraftConflict):
            review_draft(actor=self.reviewer, draft_id=draft.pk, **{**self.review_data(draft), 'reason': 'x' * 12 + '\ud800'})
        for obj in [draft, review]:
            with self.assertRaises(ValidationError): obj.save()
            with self.assertRaises(ValidationError): obj.delete()

    def test_revisions_preserve_parent_do_not_inherit_review_and_can_branch(self):
        root = self.create()
        review_draft(actor=self.reviewer, draft_id=root.pk, **self.review_data(root))
        self.client.force_login(self.author)
        revision_url = reverse('staff_clinical_revise', args=[root.pk])
        form = self.client.get(revision_url)
        self.assertContains(form, 'نسخه جدید پیش‌نویس')
        payload = {**self.form_data(), 'title': 'عنوان اصلاح‌شده', 'expected_parent_hash': root.payload_sha256,
                   'change_reason': 'این یک اصلاح ساختگی برای آزمون است.'}
        response = self.client.post(revision_url, payload)
        child = ClinicalDraft.objects.exclude(pk=root.pk).get()
        self.assertRedirects(response, reverse('staff_clinical_detail', args=[child.pk]))
        self.assertEqual(child.parent_id, root.pk); self.assertEqual(child.parent_payload_sha256, root.payload_sha256)
        self.assertEqual(child.reviews.count(), 0); self.assertEqual(child.author, self.author)
        self.assertEqual(root.title, 'عنوان ساختگی')
        branch = create_draft(actor=self.author, data=self.data, parent_id=root.pk, expected_parent_hash=root.payload_sha256,
                              change_reason='شاخه ساختگی برای آزمون بیشتر')
        self.assertNotEqual(child.pk, branch.pk)
        self.assertTrue(valid_draft(child)); self.assertTrue(valid_draft(branch))
        self.assertContains(self.client.get(reverse('staff_clinical_detail', args=[root.pk])), reverse('staff_clinical_detail', args=[child.pk]))
        self.assertContains(self.client.get(reverse('staff_clinical_detail', args=[child.pk])), reverse('staff_clinical_detail', args=[root.pk]))
        with self.assertRaises(DraftError):
            create_draft(actor=self.author, data={**self.data, 'audience': 'professional'}, parent_id=root.pk,
                         expected_parent_hash=root.payload_sha256, change_reason='دلیل ساختگی برای آزمون')
        with self.assertRaises(DraftConflict):
            create_draft(actor=self.author, data=self.data, parent_id=root.pk, expected_parent_hash='0' * 64,
                         change_reason='دلیل ساختگی برای آزمون')
        with self.assertRaises(DraftConflict):
            create_draft(actor=self.author, data=self.data, parent_id=999, expected_parent_hash='0' * 64,
                         change_reason='دلیل ساختگی برای آزمون')

    def test_revision_form_rejects_changed_subject_and_stale_parent_hash(self):
        root = self.create()
        self.client.force_login(self.author)
        url = reverse('staff_clinical_revise', args=[root.pk])
        data = {**self.form_data(), 'expected_parent_hash': root.payload_sha256,
                'change_reason': 'تغییر ساختگی برای آزمون بیشتر'}
        response = self.client.post(url, {**data, 'subject': 'موضوع متفاوت'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'برای موضوع یا مخاطب متفاوت پیش‌نویس جدید بسازید')
        response = self.client.post(url, {**data, 'expected_parent_hash': '0' * 64})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'عملیات متوقف شد', status_code=409)
        self.assertEqual(ClinicalDraft.objects.count(), 1)

    def test_immediate_parent_check_does_not_certify_earlier_ancestry(self):
        root = self.create()
        child = create_draft(actor=self.author, data=self.data, parent_id=root.pk, expected_parent_hash=root.payload_sha256,
                             change_reason='تغییر ساختگی برای آزمون بیشتر')
        grandchild = create_draft(actor=self.author, data=self.data, parent_id=child.pk, expected_parent_hash=child.payload_sha256,
                                  change_reason='تغییر دوم ساختگی برای آزمون بیشتر')
        ClinicalDraft.objects.filter(pk=root.pk).update(statement='متن ناسازگار')
        child = ClinicalDraft.objects.select_related('parent').get(pk=child.pk)
        grandchild = ClinicalDraft.objects.select_related('parent').get(pk=grandchild.pk)
        self.assertFalse(valid_draft(child))
        self.assertTrue(valid_draft(grandchild))  # only the immediate parent payload is checked

    def test_other_queues_show_clinical_link_only_with_permission(self):
        price = Permission.objects.get(content_type__app_label='pricing', codename='view_pricecandidate')
        self.viewer.user_permissions.add(price)
        self.client.force_login(get_user_model().objects.get(pk=self.viewer.pk))
        self.assertContains(self.client.get(reverse('staff_prices')), reverse('staff_clinical_drafts'))
        user = get_user_model().objects.create_user('clinical-no-access', is_staff=True)
        user.user_permissions.add(price)
        self.client.force_login(user)
        self.assertNotContains(self.client.get(reverse('staff_prices')), reverse('staff_clinical_drafts'))
        self.assertEqual(self.client.get(reverse('staff_clinical_drafts')).status_code, 403)

    def test_tampering_hides_content_and_blocks_review_and_revision(self):
        root = self.create()
        child = create_draft(actor=self.author, data=self.data, parent_id=root.pk, expected_parent_hash=root.payload_sha256,
                             change_reason='دلیل تغییر ساختگی برای آزمون')
        original_hash = child.payload_sha256
        ClinicalDraft.objects.filter(pk=root.pk).update(statement='متن تغییر یافته بدون اثر انگشت')
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('staff_clinical_detail', args=[child.pk]))
        self.assertContains(response, 'متن، ارجاع، اصلاح و بازبینی مخفی شدند')
        self.assertNotContains(response, self.data['statement']); self.assertNotContains(response, self.data['reference_url'])
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[child.pk]), self.review_data(child)).status_code, 409)
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)
        self.client.force_login(self.author)
        self.assertEqual(self.client.get(reverse('staff_clinical_revise', args=[child.pk])).status_code, 409)
        self.assertEqual(child.payload_sha256, original_hash)
        queue = self.client.get(reverse('staff_clinical_drafts'))
        self.assertNotContains(queue, self.data['title'])
        fake = SimpleNamespace(**draft_data(child), pk=child.pk, parent_id=None, parent_payload_sha256='', change_reason='', payload_sha256='a' * 64)
        fake.statement = '\ud800'; self.assertFalse(valid_payload(fake))

    def test_latest_review_audience_filters_pagination_and_large_ids(self):
        first = self.create(); other = self.create(audience='professional', title='نسخه دوم ساختگی')
        event = review_draft(actor=self.reviewer, draft_id=first.pk, **self.review_data(first, 'defer'))
        review_draft(actor=self.reviewer, draft_id=first.pk, **self.review_data(first, 'reject', event.pk))
        for i in range(24): self.create(title=f'نمونه ساختگی {i}')
        self.client.force_login(self.viewer)
        page = self.client.get(reverse('staff_clinical_drafts'), {'status': 'pending', 'audience': 'patient'})
        self.assertEqual(page.context['page'].paginator.count, 24); self.assertEqual(len(page.context['page']), 20)
        self.assertContains(page, 'audience=patient&amp;status=pending&amp;page=2')
        self.assertEqual(len(self.client.get(reverse('staff_clinical_drafts'), {'status': 'pending', 'audience': 'patient', 'page': 2}).context['page']), 4)
        self.assertEqual([item.pk for item in self.client.get(reverse('staff_clinical_drafts'), {'status': 'reject'}).context['page']], [first.pk])
        self.assertEqual([item.pk for item in self.client.get(reverse('staff_clinical_drafts'), {'audience': 'professional'}).context['page']], [other.pk])
        self.assertEqual(self.client.get(reverse('staff_clinical_drafts'), {'status': '<script>'}).status_code, 400)
        self.assertEqual(self.client.get(reverse('staff_clinical_drafts'), {'audience': 'bad'}).status_code, 400)
        for name in ['staff_clinical_detail', 'staff_clinical_revise', 'staff_clinical_review']:
            url = reverse(name, args=[9223372036854775808])
            self.client.force_login(self.author if name != 'staff_clinical_review' else self.reviewer)
            response = self.client.post(url) if name == 'staff_clinical_review' else self.client.get(url)
            self.assertEqual(response.status_code, 404); self.assert_private(response)

    def test_children_are_capped_and_review_not_inherited(self):
        root = self.create()
        for i in range(12):
            create_draft(actor=self.author, data={**self.data, 'title': f'تغییر ساختگی {i}'}, parent_id=root.pk,
                         expected_parent_hash=root.payload_sha256, change_reason='اصلاح ساختگی برای آزمون')
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_detail', args=[root.pk]))
        self.assertEqual(len(response.context['children']), 10)
        self.assertTrue(response.context['children_limited']); self.assertContains(response, 'فقط ۱۰ نسخه مستقیم اخیر')
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)

    def test_exact_source_claim_hint_has_separate_permission(self):
        self.author.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources', codename__in=['view_sourceclaim', 'add_sourceclaim']))
        author = get_user_model().objects.get(pk=self.author.pk)
        claim, _ = record_claim(actor=author, data={'source_name': 'منبع ساختگی', 'source_url': self.data['reference_url'],
            'owner': 'مالک فرضی', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
            'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
            'starts_on': None, 'expires_on': None})
        draft = self.create()
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertContains(response, 'مجوز جداگانه نیاز است')
        self.assertNotContains(response, reverse('staff_source_detail', args=[claim.pk]))
        self.client.force_login(author)
        response = self.client.get(reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertContains(response, reverse('staff_source_detail', args=[claim.pk]))
        self.assertContains(response, 'مجوز یا صحت مرجع را ثابت نمی‌کند')

    def test_csrf_methods_and_escaping(self):
        author = Client(enforce_csrf_checks=True); author.force_login(self.author)
        url = reverse('staff_clinical_create')
        payload = self.form_data({**self.data, 'statement': '<script>alert(1)</script>'})
        self.assertEqual(author.post(url, payload).status_code, 403)
        author.get(url); payload['csrfmiddlewaretoken'] = author.cookies['csrftoken'].value
        self.assertEqual(author.post(url, payload).status_code, 302)
        draft = ClinicalDraft.objects.get()
        revision_url = reverse('staff_clinical_revise', args=[draft.pk])
        revision = {**payload, 'expected_parent_hash': draft.payload_sha256, 'change_reason': 'تغییر ساختگی برای تست صرفاً'}
        revision.pop('csrfmiddlewaretoken'); self.assertEqual(author.post(revision_url, revision).status_code, 403)
        reviewer = Client(enforce_csrf_checks=True); reviewer.force_login(self.reviewer)
        review_url = reverse('staff_clinical_review', args=[draft.pk])
        self.assertEqual(reviewer.post(review_url, self.review_data(draft)).status_code, 403)
        detail = reviewer.get(reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertContains(detail, '&lt;script&gt;alert(1)&lt;/script&gt;'); self.assertNotContains(detail, '<script>alert(1)</script>')
        data = self.review_data(draft); data['csrfmiddlewaretoken'] = reviewer.cookies['csrftoken'].value
        self.assertEqual(reviewer.post(review_url, data).status_code, 302)
        self.assertEqual(reviewer.get(review_url).status_code, 405)
        self.assertEqual(reviewer.post(reverse('staff_clinical_drafts')).status_code, 403)  # CSRF middleware first
        self.assertEqual(reviewer.head(reverse('staff_clinical_drafts')).status_code, 200)

    def test_db_constraints_prevent_invalid_audience_decision_and_parent_fields(self):
        draft = self.create()
        for changes in [dict(audience='invalid'), dict(parent=None, parent_payload_sha256='a' * 64), dict(parent=draft, parent_payload_sha256='', change_reason='')]:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                ClinicalDraft.objects.filter(pk=draft.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClinicalDraftReview.objects.create(draft=draft, reviewer=self.reviewer, decision='approve', reason='fake', draft_payload_sha256='a' * 64, review_snapshot={})
