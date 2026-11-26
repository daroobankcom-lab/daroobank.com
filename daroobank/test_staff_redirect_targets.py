"""Caller-controlled redirect targets on the staff surface; synthetic evidence.

Every staff route that denies an anonymous request answers with a 302 to the login
page, and both authentication endpoints accept a caller-supplied `next`. That makes
the redirect target the one part of the staff surface whose value comes straight
from the request, so it is probed here with hostile values: protocol-relative and
absolute URLs, backslash variants, `javascript:` and `data:` schemes, embedded
userinfo, percent-encoded and traversal forms.

The suite records what the code actually does with each of them:

* an unsafe `next` never becomes a redirect target — login falls back to the staff
  workspace and logout to the home page;
* only the `next` field is consulted, and the request body wins over the query;
* an anonymous request to any of the 41 staff routes always lands on the login page
  itself, with the original staff URL — not the hostile value — as the return target;
* following a redirect chain never leaves this host and never reaches a 5xx;
* the login form echoes only the *validated* target, so a hostile value renders as
  an empty hidden input instead of being reflected into the page;
* a `next` value Django's validator considers safe is honoured, after
  `iri_to_uri` encoding, which is recorded here rather than assumed away (see the
  ADR's limitations).

It is not a redirect-policy review: it pins current behavior under the synthetic
test configuration.
"""
from urllib.parse import parse_qs, quote, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils.encoding import iri_to_uri

from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES
from .test_staff_authorization_objects import COUNTED_MODELS

PASSWORD = 'synthetic-only'
USERNAME = 'redirect-targets-staff'

# Values that must never be used as a redirect target and must never be echoed.
HOSTILE_NEXT = (
    '//evil.example/',
    '///evil.example/',
    'https://evil.example/',
    'http://evil.example/',
    'https:/evil.example',
    '/\\evil.example/',
    '\\\\evil.example',
    'javascript:alert(1)',
    'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
    'https://user@evil.example/',
    'HTTPS://EVIL.EXAMPLE/',
    ' //evil.example/',
)
# Values Django's `url_has_allowed_host_and_scheme` accepts; they are honoured
# verbatim, so the suite pins exactly what is emitted for each of them.
PASSTHROUGH_NEXT = {
    '': None,                                            # falls back to the default target
    '/': '/',
    '/staff/prices/': '/staff/prices/',
    'staff/prices/': 'staff/prices/',
    '/%2f%2fevil.example/': '/%2f%2fevil.example/',
    '/staff/../../evil': '/staff/../../evil',
    'https%3A%2F%2Fevil.example%2F': 'https%3A%2F%2Fevil.example%2F',
    '/staff/prices/?next=https://evil.example/': '/staff/prices/?next=https://evil.example/',
    # HTML metacharacters survive validation; they are escaped in the form and
    # IRI-encoded on the way into the Location header.
    '"><script>alert(1)</script>': '"><script>alert(1)</script>',
}
# Field names that must NOT be treated as a redirect target.
OTHER_FIELDS = ('return_to', 'redirect', 'returnUrl', 'next_page', 'continue', 'url', 'target', 'destination')
ALLOWED_STATUSES = frozenset({200, 302, 400, 403, 404, 405, 409})


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffRedirectTargetTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.account = User.objects.create_user(USERNAME, password=PASSWORD, is_staff=True)
        cls.account.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))

    def setUp(self):
        self.login = reverse('staff_login')
        self.logout = reverse('staff_logout')
        self.workspace = reverse('staff_workspace')
        self.home = reverse('home')

    def credentials(self):
        return {'username': USERNAME, 'password': PASSWORD}

    def routes(self):
        for name, kwargs, _method, _requirement in ROUTES:
            yield name, (reverse(name, kwargs=kwargs) if kwargs else reverse(name))

    def assert_same_host_target(self, location, allowed_paths, label):
        parsed = urlparse(location)
        self.assertEqual(parsed.netloc, '', f'{label}: redirect names a host: {location!r}')
        self.assertEqual(parsed.scheme, '', f'{label}: redirect carries a scheme: {location!r}')
        self.assertNotIn('evil.example', parsed.path, f'{label}: {location!r}')
        self.assertFalse(parsed.path.startswith('//'), f'{label}: protocol-relative target {location!r}')
        self.assertIn(parsed.path, allowed_paths, f'{label}: unexpected target {location!r}')

    def test_a_hostile_next_never_becomes_the_login_target(self):
        for value in HOSTILE_NEXT + ('',):
            with self.subTest(next=value):
                response = Client().post(self.login, {**self.credentials(), 'next': value})
                self.assertEqual(response.status_code, 302)
                self.assert_same_host_target(response['Location'], {self.workspace}, 'login')
        # A failed login never redirects, whatever the requested target.
        for value in HOSTILE_NEXT:
            with self.subTest(next=value):
                response = Client().post(self.login, {'username': USERNAME, 'password': 'wrong', 'next': value})
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('Location', response.headers)

    def test_a_hostile_next_never_becomes_the_logout_target(self):
        for value in HOSTILE_NEXT + ('',):
            with self.subTest(next=value):
                client = Client()
                client.force_login(self.account)
                response = client.post(self.logout, {'next': value})
                self.assertEqual(response.status_code, 302)
                self.assert_same_host_target(response['Location'], {self.home}, 'logout')
        # Logout refuses every method except POST, so a hostile target cannot be
        # smuggled through a link the user merely clicks.
        for value in HOSTILE_NEXT:
            with self.subTest(next=value):
                client = Client()
                client.force_login(self.account)
                self.assertEqual(client.get(f'{self.logout}?next={quote(value, safe="")}').status_code, 405)

    def test_a_safe_next_is_honoured_verbatim_by_both_endpoints(self):
        for value, expected in PASSTHROUGH_NEXT.items():
            with self.subTest(next=value):
                response = Client().post(self.login, {**self.credentials(), 'next': value})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'],
                                 iri_to_uri(expected) if expected is not None else self.workspace)
                client = Client()
                client.force_login(self.account)
                response = client.post(self.logout, {'next': value})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'],
                                 iri_to_uri(expected) if expected is not None else self.home)
                # Every honoured target is still a same-host path, never a URL.
                self.assertEqual(urlparse(response['Location']).netloc, '')

    def test_only_the_next_field_controls_the_target(self):
        for field in OTHER_FIELDS:
            with self.subTest(field=field):
                response = Client().post(self.login, {**self.credentials(), field: 'https://evil.example/'})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], self.workspace)
        # A duplicated query parameter resolves to its last value, which is unsafe
        # here, so the default target is used rather than the first (safe) one.
        response = Client().post(f'{self.login}?next={self.workspace}&next=https://evil.example/', self.credentials())
        self.assertEqual(response['Location'], self.workspace)
        # The request body wins over the query string.
        response = Client().post(f'{self.login}?next={quote("https://evil.example/", safe="")}',
                                 {**self.credentials(), 'next': self.workspace})
        self.assertEqual(response['Location'], self.workspace)

    def test_anonymous_requests_always_land_on_the_login_page_itself(self):
        checked = 0
        for value in HOSTILE_NEXT:
            for name, url in self.routes():
                with self.subTest(route=name, next=value):
                    response = Client().get(f'{url}?next={quote(value, safe="")}')
                    self.assertEqual(response.status_code, 302, name)
                    location = response['Location']
                    parsed = urlparse(location)
                    self.assertEqual(parsed.netloc, '', location)
                    self.assertEqual(parsed.path, self.login, location)
                    # The return target is the staff URL that was requested, with the
                    # hostile value surviving only as that URL's own query parameter.
                    nested = parse_qs(parsed.query)['next'][0]
                    self.assertTrue(nested.startswith(url), f'{name}: {nested!r}')
                    self.assertEqual(urlparse(nested).netloc, '', nested)
                    self.assertEqual(parse_qs(urlparse(nested).query).get('next', [''])[0], value, nested)
                    checked += 1
        self.assertEqual(checked, len(HOSTILE_NEXT) * len(ROUTES))

    def test_following_the_chain_never_leaves_the_host_or_errors(self):
        targets = [url for _name, url in list(self.routes())[:8]] + [self.login, self.logout]
        for value in HOSTILE_NEXT:
            for url in targets:
                with self.subTest(url=url, next=value):
                    client = Client()
                    client.force_login(self.account)
                    response = client.get(f'{url}?next={quote(value, safe="")}', follow=True)
                    self.assertIn(response.status_code, ALLOWED_STATUSES, response.redirect_chain)
                    for hop, _status in response.redirect_chain:
                        self.assertEqual(urlparse(hop).netloc, '', hop)
                        self.assertNotIn('evil.example', urlparse(hop).path, hop)

    def test_the_login_form_echoes_only_a_validated_target(self):
        for value in HOSTILE_NEXT:
            with self.subTest(next=value):
                body = Client().get(f'{self.login}?next={quote(value, safe="")}').content.decode()
                self.assertIn('<input type="hidden" name="next" value="">', body)
                self.assertNotIn('<script>alert(1)</script>', body)
        for value, expected in PASSTHROUGH_NEXT.items():
            with self.subTest(next=value):
                body = Client().get(f'{self.login}?next={quote(value, safe="")}').content.decode()
                rendered = body.split('name="next" value="', 1)[1].split('"', 1)[0]
                # The echoed value is the validated one, HTML-escaped by autoescape.
                self.assertEqual(rendered, '' if expected is None else expected.replace('&', '&amp;')
                                 .replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;'))
                self.assertNotIn('<script>alert(1)</script>', body)

    def test_the_probe_writes_nothing(self):
        before = {model: model.objects.count() for model in COUNTED_MODELS}
        for value in HOSTILE_NEXT:
            Client().post(self.login, {**self.credentials(), 'next': value})
            Client().get(f'{self.login}?next={quote(value, safe="")}')
            for _name, url in list(self.routes())[:8]:
                Client().get(f'{url}?next={quote(value, safe="")}')
        self.assertEqual({model: model.objects.count() for model in COUNTED_MODELS}, before)
