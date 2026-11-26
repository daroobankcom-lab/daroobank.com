"""Synthetic opt-in proxy scheme trust, never a network security boundary."""
import json
import os
import subprocess
import sys
from ipaddress import ip_network
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_KEY = 'synthetic-only-not-a-real-key-0123456789-abcdefghijklm'


class ProxyConfigurationTests(SimpleTestCase):
    def settings_process(self, flag, networks, debug='0'):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DAROOBANK_DEBUG=debug, DAROOBANK_SECRET_KEY=SYNTHETIC_KEY,
                   DAROOBANK_ALLOWED_HOSTS='example.org', POSTGRES_DB='synthetic',
                   POSTGRES_USER='synthetic', POSTGRES_HOST='synthetic-no-server', POSTGRES_PORT='5432')
        if flag is not None:
            env['DAROOBANK_TRUST_PROXY_SSL_HEADER'] = flag
        if networks is not None:
            env['DAROOBANK_TRUSTED_PROXY_CIDRS'] = networks
        script = ('import json; from daroobank import settings; '
                  'print(json.dumps([settings.SECURE_PROXY_SSL_HEADER, '
                  '[str(n) for n in settings.TRUSTED_PROXY_SCHEME_NETWORKS]]))')
        return subprocess.run([sys.executable, '-c', script], env=env, cwd=ROOT, timeout=10,
                              capture_output=True, text=True)

    def test_default_off_and_exact_opt_in(self):
        for flag in (None, '0', 'true'):
            with self.subTest(flag=flag):
                result = self.settings_process(flag, 'garbage')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [None, []])
        result = self.settings_process('1', '192.0.2.0/24,2001:db8::/48')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [['HTTP_X_FORWARDED_PROTO', 'https'],
                                                      ['192.0.2.0/24', '2001:db8::/48']])
        result = self.settings_process('1', 'invalid', debug='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [None, []])

    def test_real_nondebug_settings_apply_the_middleware_before_redirect(self):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='0',
                   DAROOBANK_SECRET_KEY=SYNTHETIC_KEY, DAROOBANK_ALLOWED_HOSTS='example.org',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='synthetic-no-server',
                   POSTGRES_PORT='5432', DAROOBANK_TRUST_PROXY_SSL_HEADER='1',
                   DAROOBANK_TRUSTED_PROXY_CIDRS='192.0.2.0/24')
        script = ("import django,json; django.setup(); from django.test import Client; c=Client(); "
                  "print(json.dumps([c.get('/', HTTP_HOST='example.org', HTTP_X_FORWARDED_PROTO='https', "
                  "REMOTE_ADDR=addr).status_code for addr in ['192.0.2.9','198.51.100.9']]))")
        result = subprocess.run([sys.executable, '-c', script], env=env, cwd=ROOT, timeout=15,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [200, 301])
        self.assertNotIn(SYNTHETIC_KEY, result.stdout + result.stderr)

    def test_opt_in_requires_valid_explicit_nonuniversal_networks(self):
        for networks in (None, '', ' ', '0.0.0.0/0', '::/0', '0.0.0.0/1,128.0.0.0/1',
                         '::/1,8000::/1', '192.0.2.9/24',
                         '192.0.2.1,', '127.0.0.1,garbage', 'fe80::1%eth0', '192.0.2.1\n',
                         ','.join('192.0.2.' + str(n) for n in range(33))):
            with self.subTest(networks=repr(networks)):
                result = self.settings_process('1', networks)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('DAROOBANK_TRUSTED_PROXY_CIDRS', result.stderr)
                self.assertNotIn(SYNTHETIC_KEY, result.stdout + result.stderr)


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=True,
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
                   TRUSTED_PROXY_SCHEME_NETWORKS=(ip_network('192.0.2.0/24'), ip_network('2001:db8:1::/48')))
class ProxySchemeMiddlewareTests(SimpleTestCase):
    def test_only_exact_single_scheme_from_trusted_direct_peer_is_honored(self):
        client = Client()
        cases = [
            ('192.0.2.10', 'https', 200),
            ('::ffff:192.0.2.10', 'https', 200),
            ('2001:db8:1::1234', 'https', 200),
            ('198.51.100.4', 'https', 301),
            ('2001:db8:2::1', 'https', 301),
            ('', 'https', 301),
            ('not-ip', 'https', 301),
            ('192.0.2.10', 'https,http', 301),
            ('192.0.2.10', 'https, http', 301),
            ('192.0.2.10', ' https ', 301),
            ('192.0.2.10', 'HTTPS', 301),
            ('192.0.2.10', 'http', 301),
        ]
        for addr, proto, expected in cases:
            with self.subTest(addr=addr, proto=proto):
                response = client.get(reverse('home'), REMOTE_ADDR=addr, HTTP_X_FORWARDED_PROTO=proto)
                self.assertEqual(response.status_code, expected)
                self.assertIn('Content-Security-Policy', response)

    def test_untrusted_header_cannot_downgrade_direct_https(self):
        response = Client().get(reverse('home'), secure=True, REMOTE_ADDR='198.51.100.5', HTTP_X_FORWARDED_PROTO='http')
        self.assertEqual(response.status_code, 200)

    @override_settings(TRUSTED_PROXY_SCHEME_NETWORKS=())
    def test_even_a_configured_django_header_is_stripped_without_trusted_peers(self):
        response = Client().get(reverse('home'), REMOTE_ADDR='192.0.2.10', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 301)

    @override_settings(STAFF_PORTAL_ENABLED=True)
    def test_trusted_tls_still_requires_csrf_origin_and_private_headers(self):
        client = Client(enforce_csrf_checks=True)
        addr = {'REMOTE_ADDR': '192.0.2.10', 'HTTP_X_FORWARDED_PROTO': 'https'}
        login = reverse('staff_login')
        response = client.get(login, **addr)
        self.assertEqual(response.status_code, 200)
        token = response.cookies['csrftoken'].value
        rejected = client.post(login, {'username': 'nobody', 'password': 'secret', 'csrfmiddlewaretoken': token},
                               HTTP_ORIGIN='https://attacker.example', **addr)
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(rejected['Cache-Control'], 'private, no-store, max-age=0')


@override_settings(DEBUG=False, STAFF_PORTAL_ENABLED=True, SECURE_SSL_REDIRECT=True,
                   SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True,
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
                   TRUSTED_PROXY_SCHEME_NETWORKS=(ip_network('192.0.2.0/24'),))
class ProxyLoginIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        get_user_model().objects.create_user('proxy-synthetic', password='synthetic-password', is_staff=True)

    def test_trusted_https_keeps_csrf_and_secure_session_cookie(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse('staff_login')
        proxy = {'REMOTE_ADDR': '192.0.2.10', 'HTTP_X_FORWARDED_PROTO': 'https', 'HTTP_HOST': 'testserver'}
        response = client.get(url, **proxy)
        self.assertTrue(response.cookies['csrftoken']['secure'])
        token = client.cookies['csrftoken'].value
        data = {'username': 'proxy-synthetic', 'password': 'synthetic-password', 'csrfmiddlewaretoken': token}
        self.assertEqual(client.post(url, data, **proxy).status_code, 403)
        response = client.post(url, data, HTTP_REFERER='https://testserver/staff/login/', **proxy)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_workspace'))
        self.assertTrue(response.cookies['sessionid']['secure'])
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')

    def test_forwarded_host_does_not_authorize_a_foreign_origin(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse('staff_login')
        proxy = {'REMOTE_ADDR': '192.0.2.10', 'HTTP_X_FORWARDED_PROTO': 'https',
                 'HTTP_HOST': 'testserver', 'HTTP_X_FORWARDED_HOST': 'attacker.example'}
        client.get(url, **proxy)
        token = client.cookies['csrftoken'].value
        response = client.post(url, {'username': 'proxy-synthetic', 'password': 'synthetic-password',
                                     'csrfmiddlewaretoken': token},
                               HTTP_ORIGIN='https://attacker.example', **proxy)
        self.assertEqual(response.status_code, 403)
        self.assertNotIn('_auth_user_id', client.session)

    def test_forged_scheme_from_untrusted_peer_cannot_establish_a_session(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse('staff_login')
        response = client.post(url, {'username': 'proxy-synthetic', 'password': 'synthetic-password'},
                               REMOTE_ADDR='198.51.100.7', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(response.status_code, 301)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
