"""Keep the architecture-decision index complete and navigable."""
import re
from pathlib import Path

from django.test import SimpleTestCase


class ArchitectureDecisionIndexTests(SimpleTestCase):
    def test_index_lists_each_adr_once_in_filename_order(self):
        directory = Path(__file__).resolve().parent.parent / 'docs' / 'ARCHITECTURE_DECISIONS'
        files = sorted(path.name for path in directory.glob('[0-9][0-9][0-9][0-9]-*.md'))
        text = (directory / 'README.md').read_text(encoding='utf-8')
        entries = re.findall(r'^- \[([0-9]{4}):[^\]]+\]\(([^)]+)\)', text, flags=re.MULTILINE)
        self.assertTrue(files)
        self.assertEqual([target for _, target in entries], files)
        for number, target in entries:
            with self.subTest(target=target):
                self.assertTrue(target.startswith(number + '-'))
