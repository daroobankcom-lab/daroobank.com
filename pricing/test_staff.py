from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from .models import PriceCandidate


class StaffPriceAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.viewer = user_model.objects.create_user('viewer', password='test-only-strong-passphrase', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(codename='view_pricecandidate', content_type__app_label='pricing'))
        cls.staff_no_permission = user_model.objects.create_user('staff-no-perm', password='test-only-strong-passphrase', is_staff=True)
        cls.regular = user_model.objects.create_user('regular', password='test-only-strong-passphrase')
        cls.regular.user_permissions.add(Permission.objects.get(codename='view_pricecandidate', content_type__app_label='pricing'))
        cls.inactive = user_model.objects.create_user('inactive', password='test-only-strong-passphrase', is_staff=True, is_active=False)
        cls.inactive.user_permissions.add(Permission.objects.get(codename='view_pricecandidate', content_type__app_label='pricing'))
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده فرضی', manufacturer='شرکت نمونه', strength='۵ میلی گرم',
            dosage_form='قرص', package_description='۱۰ عدد', irc='001234',
            source_name='نمونه', source_url='https://example.org/product',
        )
        cls.candidate = PriceCandidate.objects.create(
            source_name='منبع فرضی', source_url='https://example.org/feed', source_record_id='fake-1',
            payload_sha256='a' * 64, source_fields={
                'irc': '۰۰۱۲۳۴', 'manufacturer': 'شرکت نمونه', 'strength': '5 میلی گرم',
                'dosage_form': 'قرص', 'package_description': '10 عدد',
            }, original_amount='123.5', original_currency='TOMAN', amount_rial=1235,
            price_category='retail', unit='package', effective_date=date(2026, 1, 2),
            match_status='suggested', suggested_product=cls.product,
        )

    def assert_private(self, response):
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_portal_is_not_accessible_when_disabled(self):
        self.assertNotContains(self.client.get(reverse('home')), reverse('staff_login'))
        self.client.force_login(self.viewer)
        for url in [reverse('staff_login'), reverse('staff_prices'), reverse('staff_price_detail', args=[self.candidate.pk])]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assert_private(response)

    def test_anonymous_cannot_read_list_or_details(self):
        for url in [reverse('staff_prices'), reverse('staff_price_detail', args=[self.candidate.pk])]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn(reverse('staff_login'), response['Location'])
            self.assertNotContains(response, '123.5', status_code=302)
            self.assert_private(response)

    def test_staff_and_permission_both_required(self):
        for user in [self.staff_no_permission, self.regular]:
            self.client.force_login(user)
            for url in [reverse('staff_prices'), reverse('staff_price_detail', args=[self.candidate.pk])]:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)
                self.assertNotContains(response, '123.5', status_code=403)
                self.assert_private(response)
            self.client.logout()
        self.client.force_login(self.inactive)
        self.assertEqual(self.client.get(reverse('staff_prices')).status_code, 302)

    def test_group_permission_allows_viewing_without_granting_edit(self):
        group = Group.objects.create(name='data-viewers')
        group.permissions.add(Permission.objects.get(codename='view_pricecandidate', content_type__app_label='pricing'))
        self.staff_no_permission.groups.add(group)
        self.client.force_login(self.staff_no_permission)
        response = self.client.get(reverse('staff_prices'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'داده‌های این بخش هنوز تأیید یا منتشر نشده‌اند')
        self.assertContains(response, 'name="robots" content="noindex,nofollow"')
        self.assert_private(response)
        self.assertEqual(self.client.post(reverse('staff_prices')).status_code, 405)
        self.assertEqual(self.client.post(reverse('staff_price_detail', args=[self.candidate.pk])).status_code, 405)
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_viewer_sees_unverified_source_and_current_suggestion(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_price_detail', args=[self.candidate.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '123.5')
        self.assertContains(response, '1235')
        self.assertContains(response, 'پیشنهاد فعلی')
        self.assertContains(response, 'فرآورده فرضی')
        self.assertContains(response, 'این ردیف قیمت تأییدشده نیست')
        self.assert_private(response)
        self.product.strength = 'دوز متفاوت'
        self.product.save(update_fields=['strength'])
        response = self.client.get(reverse('staff_price_detail', args=[self.candidate.pk]))
        self.assertContains(response, 'بدون پیشنهاد قطعی')
        self.assertNotContains(response, 'فرآورده فرضی')
        self.assertNotContains(self.client.get(reverse('prices')), '123.5')

    def test_bad_source_fields_fail_closed_and_html_is_escaped(self):
        self.candidate.source_name = '<script>alert(1)</script>'
        self.candidate.source_url = 'javascript:alert(1)'
        self.candidate.source_fields = {'irc': None}
        self.candidate.save()
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_price_detail', args=[self.candidate.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اطلاعات نامعتبر')
        self.assertContains(response, '&lt;script&gt;')
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(response, 'href="javascript:')

    def test_filter_and_pagination_are_bounded(self):
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('staff_prices'), {'status': 'bad'}).status_code, 400)
        for index in range(23):
            PriceCandidate.objects.create(
                source_name='نمونه', source_url='https://example.org', source_record_id=f'fake-{index}',
                payload_sha256='b' * 64, source_fields=self.candidate.source_fields,
                original_amount='10', original_currency='RIAL', amount_rial=10,
                price_category='retail', unit='package', match_status='unmatched',
            )
        response = self.client.get(reverse('staff_prices'), {'status': 'unmatched'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page'].object_list), 20)
        self.assertContains(response, 'صفحه بعد')
        self.assertEqual(len(self.client.get(reverse('staff_prices'), {'status': 'unmatched', 'page': 2}).context['page'].object_list), 3)

    def test_csrf_login_logout_and_safe_redirect(self):
        client = Client(enforce_csrf_checks=True)
        login = reverse('staff_login')
        self.assertEqual(client.post(login, {'username': 'viewer', 'password': 'test-only-strong-passphrase'}).status_code, 403)
        response = client.get(login)
        self.assert_private(response)
        token = response.cookies['csrftoken'].value
        response = client.post(login + '?next=https://evil.example/', {
            'username': 'viewer', 'password': 'test-only-strong-passphrase',
            'csrfmiddlewaretoken': token, 'next': 'https://evil.example/',
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_workspace'))
        self.assertEqual(client.get(reverse('staff_logout')).status_code, 405)
        self.assertEqual(client.post(reverse('staff_logout')).status_code, 403)
        client.get(reverse('staff_prices'))
        token = client.cookies['csrftoken'].value
        self.assertEqual(client.post(reverse('staff_logout'), {'csrfmiddlewaretoken': token}).status_code, 302)
        self.assertEqual(client.get(reverse('staff_prices')).status_code, 302)

    @override_settings(STAFF_PORTAL_ENABLED=True, CSRF_TRUSTED_ORIGINS=[])
    def test_csrf_origin_and_secure_referer_with_real_token(self):
        # A supplied token and cookie are not enough when the Origin is hostile.
        login = reverse('staff_login')
        cases = [
            ('same origin', False, {'HTTP_ORIGIN': 'http://testserver'}, 302),
            ('null origin', False, {'HTTP_ORIGIN': 'null'}, 403),
            ('other origin', False, {'HTTP_ORIGIN': 'https://attacker.example'}, 403),
            ('wrong port', False, {'HTTP_ORIGIN': 'http://testserver:8080'}, 403),
            ('secure same origin', True, {'HTTP_ORIGIN': 'https://testserver'}, 302),
            ('secure same-origin referer', True, {'HTTP_REFERER': 'https://testserver/staff/login/'}, 302),
            ('secure missing referer', True, {}, 403),
            ('secure foreign referer', True, {'HTTP_REFERER': 'https://attacker.example/'}, 403),
            ('secure downgrade referer', True, {'HTTP_REFERER': 'http://testserver/staff/login/'}, 403),
        ]
        for label, secure, headers, expected in cases:
            with self.subTest(label=label):
                client = Client(enforce_csrf_checks=True)
                response = client.get(login, secure=secure)
                token = response.cookies['csrftoken'].value
                response = client.post(login, {'username': 'viewer', 'password': 'test-only-strong-passphrase',
                                                'csrfmiddlewaretoken': token}, secure=secure, **headers)
                self.assertEqual(response.status_code, expected)
                self.assert_private(response)
                result = client.get(reverse('staff_prices'), secure=secure)
                self.assertEqual(result.status_code, 200 if expected == 302 else 302)

    def test_wrong_password_and_staff_pages_not_indexed(self):
        response = self.client.post(reverse('staff_login'), {'username': 'viewer', 'password': 'incorrect'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'نام کاربری یا گذرواژه صحیح نیست')
        self.assert_private(response)
        sitemap = self.client.get(reverse('sitemap')).content.decode()
        self.assertNotIn('/staff/', sitemap)
