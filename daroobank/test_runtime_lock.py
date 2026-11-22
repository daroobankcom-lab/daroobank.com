"""Offline checks for the direct-pin/lock consistency guard."""
from pathlib import Path

from django.test import SimpleTestCase

from tools.verify_runtime_lock import verify

ROOT = Path(__file__).resolve().parent.parent


class RuntimeLockTests(SimpleTestCase):
    def test_current_direct_requirements_match(self):
        verify((ROOT / 'requirements.in').read_text(encoding='utf-8'),
               (ROOT / 'requirements.txt').read_text(encoding='utf-8'))

    def test_exact_pins_and_extras_match_after_normalization(self):
        verify('Example_Pkg[Extra_B,extra-a]==1.2\n',
               'example-pkg[extra-a,extra-b]==1.2 \\\n    --hash=sha256:abcd\nother==3\n')

    def test_missing_changed_extras_and_invalid_input_fail_closed(self):
        for direct, locked in [
            ('x==1', 'y==1'), ('x==1', 'x==2'), ('x[a]==1', 'x==1'),
            ('x>=1', 'x==1'), ('', 'x==1'), ('x==1\nx==1', 'x==1'),
            ('x==1', 'x==1\nx==1'), ('x==1', 'x==1; sys_platform == "win32"'),
            ('-r other.txt', 'x==1'),
            ('x==1; python_version < "3.13"', 'x==1'),
        ]:
            with self.subTest(direct=direct, locked=locked), self.assertRaises(ValueError):
                verify(direct, locked)
