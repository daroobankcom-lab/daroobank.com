"""Selected in-flight staging write boundaries; not global revocation."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from catalog.intake import parse_product_csv
from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from ingestion.models import ImportReceipt
from pricing.importer import parse_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes

PRODUCT = dict(source_record_id='one', name_fa='فرآورده فرضی', name_en='Synthetic', manufacturer='سازنده فرضی',
               strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
PRICE = dict(source_record_id='one', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
             dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
             category='retail', unit='package', effective_date='', source_published_date='')


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightStageWriteTests(TransactionTestCase):
    def setUp(self):
        self.stager = get_user_model().objects.create_user('synthetic-inflight-stager', password='synthetic-only',
                                                           is_staff=True)
        for app in ('catalog', 'pricing'):
            self.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label=app))
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.stager)
        self.assertEqual(self.client.get(reverse('staff_product_upload')).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff_price_upload')).status_code, 200)

    def token(self):
        return self.client.cookies['csrftoken'].value

    def upload(self, route, name, url, content):
        return {'source_name': name, 'source_url': url, 'action': 'stage', 'rights_attested': 'on',
                'csv_file': SimpleUploadedFile('synthetic.csv', content, content_type='text/csv')}

    def product_upload(self):
        return self.upload('staff_product_upload', 'منبع ساختگی', 'https://example.org/inflight-product',
                           make_csv([PRODUCT]))

    def price_upload(self):
        return self.upload('staff_price_upload', 'منبع ساختگی', 'https://example.org/inflight-price',
                           csv_bytes([PRICE]))

    def _paused_post(self, path, payload, target, original, change_account, candidates):
        """Park one CSRF-valid staging POST before its guarded transaction."""
        ready, resume = Event(), Event()

        def paused(*args, **kwargs):
            # The view's own permission checks have already passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic in-flight upload did not resume')
            return original(*args, **kwargs)

        def post_upload():
            close_old_connections()
            try:
                return self.client.post(path, payload, HTTP_X_CSRFTOKEN=self.token())
            finally:
                close_old_connections()

        with patch(target, side_effect=paused):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_upload)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic upload did not reach parsing')
                    change_account()
                    self.assertFalse(candidates.objects.exists())
                    self.assertFalse(ImportReceipt.objects.exists())
                finally:
                    resume.set()
                return future.result(timeout=20)

    def invalidate_and_reactivate(self):
        current = get_user_model().objects.get(pk=self.stager.pk)
        current.is_active = False
        current.set_unusable_password()
        current.save(update_fields=['is_active', 'password'])
        get_user_model().objects.filter(pk=self.stager.pk).update(is_active=True)

    def disable_then_reactivate(self):
        current = get_user_model().objects.get(pk=self.stager.pk)
        current.is_active = False
        current.save(update_fields=['is_active'])
        get_user_model().objects.filter(pk=self.stager.pk).update(is_active=True)

    def test_password_invalidation_before_product_stage_guard_denies_inflight_upload(self):
        path = reverse('staff_product_upload')
        payload = self.product_upload()
        self.assertEqual(self.client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertFalse(ProductCandidate.objects.exists())
        # A fresh upload object: the rejected POST already consumed the file handle.
        response = self._paused_post(path, self.product_upload(), 'catalog.intake.parse_product_csv', parse_product_csv,
                                     self.invalidate_and_reactivate, ProductCandidate)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ProductCandidate.objects.exists())
        self.assertFalse(ImportReceipt.objects.exists())
        fresh = self.client.post(path, self.product_upload(), HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertFalse(ProductCandidate.objects.exists())

    def test_flag_only_reactivation_before_product_stage_guard_can_still_allow_inflight_upload(self):
        response = self._paused_post(reverse('staff_product_upload'), self.product_upload(),
                                     'catalog.intake.parse_product_csv', parse_product_csv,
                                     self.disable_then_reactivate, ProductCandidate)
        self.assertEqual(response.status_code, 200)
        candidate = ProductCandidate.objects.get()
        self.assertEqual(candidate.staged_by_id, self.stager.pk)
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_password_invalidation_before_price_stage_guard_denies_inflight_upload(self):
        path = reverse('staff_price_upload')
        payload = self.price_upload()
        self.assertEqual(self.client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertFalse(PriceCandidate.objects.exists())
        # A fresh upload object: the rejected POST already consumed the file handle.
        response = self._paused_post(path, self.price_upload(), 'pricing.importer.parse_csv', parse_csv,
                                     self.invalidate_and_reactivate, PriceCandidate)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PriceCandidate.objects.exists())
        self.assertFalse(ImportReceipt.objects.exists())
        fresh = self.client.post(path, self.price_upload(), HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertFalse(PriceCandidate.objects.exists())

    def test_flag_only_reactivation_before_price_stage_guard_can_still_allow_inflight_upload(self):
        response = self._paused_post(reverse('staff_price_upload'), self.price_upload(),
                                     'pricing.importer.parse_csv', parse_csv,
                                     self.disable_then_reactivate, PriceCandidate)
        self.assertEqual(response.status_code, 200)
        candidate = PriceCandidate.objects.get()
        self.assertEqual(candidate.staged_by_id, self.stager.pk)
        self.assertEqual(ImportReceipt.objects.count(), 1)
