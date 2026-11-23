"""Offline tests of the synthetic-browser CI failure summary."""
from django.test import SimpleTestCase

from tools.browser_test_diagnostics import browser_failure_annotation


class BrowserFailureAnnotationTests(SimpleTestCase):
    def test_assertion_uses_only_fixed_category_exit_and_stack_line(self):
        stderr = ('AssertionError [ERR_ASSERTION]: secret-query\n'
                  '    at run (/home/runner/work/project/tests/browser/smoke.cjs:250:17)\n')
        annotation = browser_failure_annotation(1, stderr)
        self.assertEqual(annotation, '::error file=tests/browser/smoke.cjs,line=250::'
                         'Isolated synthetic browser test exited with code 1; category: assertion. '
                         'See the job log for details.')
        self.assertNotIn('secret-query', annotation)
        self.assertNotIn('/home/runner', annotation)

    def test_no_untrusted_output_in_annotation_and_unknown_failures(self):
        stderr = '::error file=evil::SECRET\nunknown failure on https://example.org/private?q=SECRET\n'
        annotation = browser_failure_annotation(-11, stderr)
        self.assertEqual(annotation, '::error file=tests/browser/smoke.cjs::'
                         'Isolated synthetic browser test exited with code -11; category: other or unknown. '
                         'See the job log for details.')
        self.assertNotIn('SECRET', annotation)
        self.assertNotIn('evil', annotation)

    def test_timeout_and_playwright_timeout(self):
        self.assertIn('test timed out; category: other or unknown', browser_failure_annotation(None, ''))
        self.assertIn('category: timeout', browser_failure_annotation(1, 'page.waitForURL: Timeout 30000ms exceeded'))
        self.assertIn('category: timeout', browser_failure_annotation(1, 'TimeoutError: timed out'))

    def test_browser_closed_and_windows_stack(self):
        annotation = browser_failure_annotation(1, 'TargetClosedError\n    at run (C:\\work\\smoke.cjs:12:9)\n')
        self.assertIn('smoke.cjs,line=12::', annotation)
        self.assertIn('category: browser closed', annotation)
        self.assertNotIn('C:', annotation)
