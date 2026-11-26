"""Selected sanitized CI failure annotation handling for synthetic tests."""
import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

from django.test import SimpleTestCase

from tools.report_synthetic_test_failures import main


class CiFailureReportingTests(SimpleTestCase):
    def report(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.log'
            path.write_text(content, encoding='utf-8')
            output = io.StringIO()
            with redirect_stdout(output):
                main(path)
            return output.getvalue()

    def test_only_names_not_subtest_values_or_traceback_are_annotated(self):
        canary = 'synthetic-private-subtest-canary'
        output = self.report('FAIL: test_boundary (daroobank.test_module.Case) (value=' + canary + ')\n'
                             'FAIL: test_boundary (daroobank.test_module.Case) (value=another)\n'
                             'ERROR: test_second (catalog.tests.OtherCase)\n'
                             '  password=' + canary + '\n'
                             'FAIL: test_bad (::error::inject)\n')
        self.assertEqual(output.splitlines(), [
            '::error title=Synthetic test FAIL::daroobank.test_module.Case.test_boundary',
            '::error title=Synthetic test ERROR::catalog.tests.OtherCase.test_second',
        ])
        self.assertNotIn(canary, output)

    def test_unrecognized_output_produces_fixed_fallback(self):
        output = self.report('random synthetic-private-canary\n')
        self.assertEqual(output, '::error title=Synthetic test failure::No parseable test name; inspect the CI job log.\n')

    def test_annotation_count_is_bounded(self):
        content = ''.join(f'FAIL: test_{i} (test_module.Case)\n' for i in range(50))
        self.assertEqual(len(self.report(content).splitlines()), 30)
