"""Offline tests: no registry access and no modification of lock files."""
import io
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from django.test import SimpleTestCase

from tools import check_lock_metadata as checker

A, B, C = 'a' * 64, 'b' * 64, 'c' * 64


def metadata(name='demo-pkg', version='1.2', hashes=(A, B)):
    return {'info': {'name': name, 'version': version},
            'urls': [{'digests': {'sha256': value}} for value in hashes]}


class LockMetadataTests(SimpleTestCase):
    def test_project_locks_parse_offline(self):
        for path in checker.LOCKS:
            with self.subTest(path=path):
                self.assertTrue(checker.parse_lock(path.read_text(encoding='utf-8')))

    def test_match_and_mismatches_include_conditional_requirements(self):
        records = checker.parse_lock(
            f'Demo_Pkg[extra]==1.2; sys_platform == "win32" \\\n'
            f'    --hash=sha256:{A} \\\n    --hash=sha256:{B}\n')
        self.assertEqual(checker.compare(records, lambda *_: metadata()), [])
        self.assertEqual(checker.compare(records, lambda *_: metadata(hashes=(B, C))),
                         [('Demo_Pkg', '1.2', {C}, {A})])

    def test_bad_locks_rejected(self):
        invalid = ['', 'x==1', f'x==1 \\\n--hash=sha256:{A} \\\n',
                   f'x==1 \\\n--hash=sha256:{A} \\\n--hash=sha256:{A}\n',
                   'x==1 \\\n--hash=sha256:abcd\n',
                   f'x==1 \\\n--hash=sha256:{A}\nx==2 \\\n--hash=sha256:{B}\n',
                   f'x==1 \\\n\n--hash=sha256:{A}\n', '-r other.txt\n']
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(ValueError):
                checker.parse_lock(text)

    def test_bad_or_empty_metadata_fails(self):
        for data in [{}, metadata(name='other'), metadata(version='2'),
                     metadata(hashes=()), metadata(hashes=('not-a-hash',)),
                     {'info': {'name': 'demo-pkg', 'version': '1.2'}, 'urls': [{}]},
                     {'info': None, 'urls': []}]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                checker.release_hashes(data, 'demo-pkg', '1.2')

    def test_main_is_nonzero_on_mismatch_or_registry_failure(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with patch.object(checker, 'compare', return_value=[('x', '1', {A}, {B})]):
                self.assertEqual(checker.main(), 1)
            with patch.object(checker, 'compare', side_effect=OSError('registry unavailable')):
                self.assertEqual(checker.main(), 1)
            with patch.object(checker, 'compare', return_value=[]):
                self.assertEqual(checker.main(), 0)

    def test_fetch_uses_fixed_pypi_endpoint_timeout_and_size_limit(self):
        class Response:
            def __init__(self, data):
                self.data = data

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, limit):
                self.limit = limit
                return self.data

        response = Response(b'{"info": {}, "urls": []}')
        with patch.object(checker, 'urlopen', return_value=response) as urlopen:
            self.assertEqual(checker.fetch_release('demo-pkg', '1.2'), {'info': {}, 'urls': []})
            urlopen.assert_called_once_with('https://pypi.org/pypi/demo-pkg/1.2/json', timeout=20)
            self.assertEqual(response.limit, checker.MAX_METADATA_BYTES + 1)
        with patch.object(checker, 'urlopen', return_value=Response(b'x' * (checker.MAX_METADATA_BYTES + 1))):
            with self.assertRaises(ValueError):
                checker.fetch_release('demo-pkg', '1.2')
