"""Synthetic sample downloads are fixed, private, permission-gated, and previewable."""
import csv
import io
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.intake import parse_product_csv
from catalog.models import ProductCandidate
from ingestion.models import ImportReceipt
from pricing.importer import parse_csv
from pricing.models import PriceCandidate


@override_settings(STAFF_PORTAL_ENABLED=True)
class SyntheticSampleDownloadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.both = user.objects.create_user('synthetic-sample-both', is_staff=True)
        cls.viewer = user.objects.create_user('synthetic-sample-view', is_staff=True)
        cls.add_only = user.objects.create_user('synthetic-sample-add', is_staff=True)
        cls.nonstaff = user.objects.create_user('synthetic-sample-nonstaff', is_staff=False)
        cls.inactive = user.objects.create_user('synthetic-sample-inactive', is_staff=True, is_active=False)
        for app, model in (('catalog', 'productcandidate'), ('pricing', 'pricecandidate')):
            perms = Permission.objects.filter(content_type__app_label=app, codename__in=[f'view_{model}', f'add_{model}'])
            cls.both.user_permissions.add(*perms)
            cls.viewer.user_permissions.add(*perms.filter(codename=f'view_{model}'))
            cls.add_only.user_permissions.add(*perms.filter(codename=f'add_{model}'))
            cls.nonstaff.user_permissions.add(*perms)
            cls.inactive.user_permissions.add(*perms)

    @staticmethod
    def cases():
        return (
            ('staff_product_sample', 'staff_product_upload', 'product_candidates.synthetic.csv', ProductCandidate),
            ('staff_price_sample', 'staff_price_upload', 'price_candidates.synthetic.csv', PriceCandidate),
        )

    def assert_private(self, response):
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_permission_gate_methods_and_disabled_portal(self):
        for route, _, _, _ in self.cases():
            url = reverse(route)
            self.client.logout()
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assert_private(response)
            for actor in (self.viewer, self.add_only, self.nonstaff):
                self.client.force_login(actor)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assert_private(response)
                self.client.logout()
            self.client.force_login(self.inactive)
            self.assertNotEqual(self.client.get(url).status_code, 200)
            self.client.force_login(self.both)
            for method in (self.client.post, self.client.put):
                response = method(url)
                self.assertEqual(response.status_code, 405)
                self.assert_private(response)
            with self.settings(STAFF_PORTAL_ENABLED=False):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)
                self.assert_private(response)

    def test_permissions_are_domain_scoped_and_work_through_groups(self):
        user = get_user_model()
        product = user.objects.create_user('sample-product-only', is_staff=True)
        price = user.objects.create_user('sample-price-only', is_staff=True)
        group = Group.objects.create(name='sample-product-importers')
        group.permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
            codename__in=['view_productcandidate', 'add_productcandidate']))
        product.groups.add(group)
        price.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'add_pricecandidate']))
        for actor, allowed, denied in ((product, 'staff_product_sample', 'staff_price_sample'),
                                       (price, 'staff_price_sample', 'staff_product_sample')):
            with self.subTest(actor=actor.username):
                self.client.force_login(actor)
                self.assertEqual(self.client.get(reverse(allowed)).status_code, 200)
                self.assertEqual(self.client.get(reverse(denied)).status_code, 403)

    def test_each_file_is_exactly_the_local_sample_and_previewable(self):
        self.client.force_login(self.both)
        for route, upload_route, filename, model in self.cases():
            with self.subTest(route=route):
                url = reverse(route)
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assert_private(response)
                self.assertEqual(response['Content-Type'], 'text/csv; charset=utf-8')
                self.assertEqual(response['Content-Disposition'], f'attachment; filename="{filename}"')
                content = response.content
                self.assertEqual(content, (Path(settings.BASE_DIR) / 'examples' / filename).read_bytes())
                # A query string cannot select a different file or alter its response.
                ignored = self.client.get(url, {'filename': '../../.env', 'kind': 'other'})
                self.assertEqual(ignored.status_code, 200)
                self.assertEqual(ignored.content, content)
                self.assertEqual(ignored['Content-Disposition'], response['Content-Disposition'])
                parsed = parse_product_csv(io.BytesIO(content)) if model is ProductCandidate else parse_csv(io.BytesIO(content))
                self.assertEqual(len(parsed), 2)
                for row in csv.reader(io.StringIO(content.decode('utf-8'), newline='')):
                    for value in row:
                        self.assertFalse(value.lstrip().startswith(('=', '+', '-', '@')), 'sample is not spreadsheet-safe')
                head = self.client.head(url)
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b'')
                self.assertEqual(head['Content-Disposition'], response['Content-Disposition'])
                self.assert_private(head)
                form = self.client.get(reverse(upload_route))
                self.assertContains(form, f'href="{url}"')
                self.assertContains(form, 'فایل نمونه ساختگی')
                preview = self.client.post(reverse(upload_route), {
                    'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/synthetic',
                    'action': 'preview', 'csv_file': SimpleUploadedFile(filename, content, content_type='text/csv'),
                })
                self.assertEqual(preview.status_code, 200)
                self.assertEqual(preview.context['result']['rows'], 2)
                self.assertEqual(preview.context['result']['mode'], 'preview')
                self.assertEqual(model.objects.count(), 0)
                self.assertEqual(ImportReceipt.objects.count(), 0)
