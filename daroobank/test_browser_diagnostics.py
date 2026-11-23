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

    def test_stack_summary_includes_bounded_caller_lines_not_paths(self):
        stderr = ('AssertionError: private-label\n'
                  '    at checkKeyboardFocus (/private/smoke.cjs:71:3)\n'
                  '    at login (/private/smoke.cjs:149:3)\n'
                  '    at run (/private/smoke.cjs:269:7)\n'
                  '    at extra (/private/smoke.cjs:999:1)\n')
        annotation = browser_failure_annotation(1, stderr)
        self.assertIn('smoke.cjs,line=71::', annotation)
        self.assertIn('Caller lines: 149, 269.', annotation)
        self.assertNotIn('999', annotation)
        self.assertNotIn('private', annotation)
        self.assertNotIn('login', annotation)

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

    def test_focus_annotation_only_uses_known_labels_and_reasons(self):
        for label, detail, expected in [
            ('search 320', 'missing focus outline', 'outline missing'),
            ('scan category 390', 'not keyboard-focused', 'not keyboard-focused'),
            ('quality submit 1440', 'outline contrast below 3:1 against container', 'outline contrast below 3:1'),
            ('forced-colors acknowledgment', 'missing focus outline', 'outline missing'),
            ('login password', 'missing focus outline', 'outline missing'),
        ]:
            with self.subTest(label=label, detail=detail):
                stderr = f'AssertionError [ERR_ASSERTION]: {label}: {detail}\n    at run (/tmp/smoke.cjs:71:3)\n'
                annotation = browser_failure_annotation(1, stderr)
                self.assertIn(f'Focus check: {label} ({expected}).', annotation)
                self.assertNotIn('/tmp/', annotation)

    def test_unknown_or_injected_focus_messages_are_not_echoed(self):
        for message in ('scan start 391: missing focus outline',
                        'scan start 390: missing focus outline SECRET',
                        'scan start 390: missing focus outline::error::SECRET',
                        'SECRET: missing focus outline'):
            with self.subTest(message=message):
                annotation = browser_failure_annotation(1, f'AssertionError [ERR_ASSERTION]: {message}\n')
                self.assertNotIn('Focus check:', annotation)
                self.assertNotIn('SECRET', annotation)
                self.assertNotIn('391', annotation)

    def test_browser_closed_and_windows_stack(self):
        annotation = browser_failure_annotation(1, 'TargetClosedError\n    at run (C:\\work\\smoke.cjs:12:9)\n')
        self.assertIn('smoke.cjs,line=12::', annotation)
        self.assertIn('category: browser closed', annotation)
        self.assertNotIn('C:', annotation)
