"""Empty but CSRF-authorized staff POSTs should be bound and show errors."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductCandidate
from clinical.models import ClinicalDraft, ClinicalReferenceAssertion
from clinical.services import create_draft
from ingestion.models import ImportReceipt
from pricing.models import PriceCandidate
from sources.models import SourceClaim


@override_settings(STAFF_PORTAL_ENABLED=True)
class EmptyStaffPostTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user('synthetic-empty-author', is_staff=True)
        for app, model in (('sources', 'sourceclaim'), ('clinical', 'clinicaldraft'),
                           ('catalog', 'productcandidate'), ('pricing', 'pricecandidate')):
            cls.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label=app,
                codename__in=[f'view_{model}', f'add_{model}']))
        cls.draft = create_draft(actor=cls.actor, data={
            'subject': 'موضوع ساختگی', 'audience': 'patient', 'title': 'عنوان ساختگی',
            'statement': 'گزاره ساختگی', 'reference_title': 'ارجاع ساختگی',
            'reference_url': 'https://example.org/reference', 'reference_location': 'بخش ساختگی',
            'reference_author': '', 'reference_version': '',
            'reference_published_on': None, 'reference_accessed_on': None,
        })

    def test_get_unbound_empty_csrf_authorized_post_shows_required_errors_without_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        cases = (
            (reverse('staff_source_create'), 'source_name'),
            (reverse('staff_clinical_create'), 'subject'),
            (reverse('staff_clinical_revise', args=[self.draft.pk]), 'subject'),
            (reverse('staff_clinical_reference_create', args=[self.draft.pk]), 'reference_title'),
            (reverse('staff_product_upload'), 'csv_file'),
            (reverse('staff_price_upload'), 'csv_file'),
        )
        for url, field in cases:
            with self.subTest(url=url):
                get = client.get(url)
                self.assertEqual(get.status_code, 200)
                self.assertFalse(get.context['form'].is_bound)
                self.assertNotContains(get, 'id="staff-form-errors"')
                self.assertNotContains(get, 'خطا در فرم |')
                with_query = client.get(url + '?sample=one&sample=two')
                self.assertContains(with_query, f'action="{url}?sample=one&amp;sample=two"')
                token = client.cookies['csrftoken'].value
                denied = client.post(url, data='', content_type='application/x-www-form-urlencoded')
                self.assertEqual(denied.status_code, 403)
                response = client.post(url, data='', content_type='application/x-www-form-urlencoded', HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].is_bound)
                self.assertIn(field, response.context['form'].errors)
                self.assertContains(response, f'id_{field}_error')
                self.assertContains(response, 'id="staff-form-errors"')
                self.assertContains(response, f'href="#id_{field}"')
                self.assertContains(response, 'خطا در فرم |')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(SourceClaim.objects.count(), 0)
                self.assertEqual(ClinicalDraft.objects.count(), 1)
                self.assertEqual(ClinicalReferenceAssertion.objects.count(), 0)
                self.assertEqual(ProductCandidate.objects.count(), 0)
                self.assertEqual(PriceCandidate.objects.count(), 0)
                self.assertEqual(ImportReceipt.objects.count(), 0)
