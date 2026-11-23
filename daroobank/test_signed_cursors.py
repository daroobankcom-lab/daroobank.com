"""Signed-cursor age boundaries using synthetic values and a controlled clock."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.core import signing
from django.test import SimpleTestCase
from django.urls import reverse

from catalog import identity_lineage, quality_irc, services
from clinical import lineage as clinical_lineage
from .signed_cursors import loads_nonfuture


class SignedCursorClockTests(SimpleTestCase):
    def test_helper_checks_signature_and_both_age_boundaries(self):
        with patch('time.time', return_value=10000):
            token = signing.dumps({'key': 'synthetic'}, salt='synthetic-test')
        for now in (10000, 10000.9, 13600):
            with self.subTest(now=now), patch('time.time', return_value=now):
                self.assertEqual(loads_nonfuture(token, salt='synthetic-test', max_age=3600), {'key': 'synthetic'})
        for now in (9999, 13601):
            with self.subTest(now=now), patch('time.time', return_value=now), self.assertRaises(signing.BadSignature):
                loads_nonfuture(token, salt='synthetic-test', max_age=3600)
        with patch('time.time', return_value=10000), self.assertRaises(signing.BadSignature):
            loads_nonfuture(token + 'x', salt='synthetic-test', max_age=3600)
        with patch('time.time', return_value=10000), self.assertRaises(signing.BadSignature):
            loads_nonfuture(token, salt='wrong-salt', max_age=3600)

    def test_all_four_cursor_decoders_reject_future_tokens(self):
        anchor = SimpleNamespace(pk=100, payload_sha256='a' * 64, name_fa='Synthetic')
        current = SimpleNamespace(pk=79, payload_sha256='b' * 64)
        candidates = Mock()
        candidates.filter.return_value.only.return_value.first.return_value = anchor
        code = 'synthetic-code'
        with patch('time.time', return_value=10000):
            public = services._encode_cursor('synthetic', anchor)
            irc = signing.dumps({'anchor': 100, 'last': 79, 'code': quality_irc._digest(code)}, salt=quality_irc.CURSOR_SALT)
            identity = identity_lineage._encode('ingredient', 100, 'a' * 64, 79, 'b' * 64, 20)
            clinical = clinical_lineage._encode(anchor, current, 20)
        cases = [
            (lambda: services._decode_cursor(public, 'synthetic', candidates), services.InvalidSearchCursor),
            (lambda: quality_irc._decode_cursor(irc, 100, code), quality_irc.InvalidIRCCursor),
            (lambda: identity_lineage._decode(identity, 'ingredient', 100, 'a' * 64), identity_lineage.InvalidLineageCursor),
            (lambda: clinical_lineage._decode(clinical, anchor), clinical_lineage.InvalidLineageCursor),
        ]
        for decode, error in cases:
            for now in (9999, 13601):
                with self.subTest(error=error.__name__, now=now), patch('time.time', return_value=now):
                    with self.assertRaises(error):
                        decode()
            for now in (10000, 13600):
                with self.subTest(error=error.__name__, now=now), patch('time.time', return_value=now):
                    self.assertIsNotNone(decode())

    def test_future_public_cursor_is_generic_private_error_without_database_access(self):
        with patch('time.time', return_value=10000):
            token = services._encode_cursor('synthetic', SimpleNamespace(pk=1, name_fa='synthetic-canary'))
        for route in ('search', 'search_api'):
            for method in (self.client.get, self.client.head):
                with self.subTest(route=route, method=method.__name__), patch('time.time', return_value=9999):
                    response = method(reverse(route), {'q': 'synthetic', 'cursor': token})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response['Cache-Control'], 'no-store')
                    self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                    self.assertNotIn(token.encode(), response.content)
                    self.assertNotIn(b'synthetic-canary', response.content)
                    if route == 'search_api' and method == self.client.get:
                        self.assertEqual(response.json()['error']['code'], 'invalid_cursor')
