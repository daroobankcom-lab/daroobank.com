"""Restart links are limited to the two internal scan routes."""
from django.test import RequestFactory, SimpleTestCase

from .scan_responses import invalid_scan_response


class ScanResponseTests(SimpleTestCase):
    def test_unsupported_restart_routes_fail_before_rendering(self):
        request = RequestFactory().get('/staff/synthetic/')
        for route in ('staff_workspace', 'https://example.org/', '//example.org/', '', None):
            with self.subTest(route=route), self.assertRaises(ValueError):
                invalid_scan_response(request, restart_route=route)
