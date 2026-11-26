"""The release notes must keep one heading per entry.

Twice while documenting other work a patch script replaced a `## ` heading instead of
inserting above it, leaving an entry body with no title and no date. Nothing else in the
repository would have noticed. These assertions are cheap, need no database, and fail on
the defect rather than on the prose: every entry heading is unique and dated, and every
`**Changes:**` paragraph belongs to the heading directly above it.

This checks structure only. It cannot tell whether an entry is accurate, complete, or
honest about its own limits.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

CHANGELOG = Path(__file__).resolve().parent.parent / 'docs' / 'CHANGELOG.md'
HEADING = re.compile(r'\A## (\d{4}-\d{2}-\d{2}) — (.+)\Z')


class ReleaseNotesStructureTests(SimpleTestCase):
    def test_entry_headings_are_unique_dated_and_newest_first(self):
        headings = [line for line in CHANGELOG.read_text(encoding='utf-8').splitlines()
                    if line.startswith('## ')]
        self.assertGreater(len(headings), 100, 'the release notes lost their history')
        self.assertEqual(len(set(headings)), len(headings), 'two entries share a heading')
        dated = []
        undated = []
        for heading in headings:
            match = HEADING.match(heading)
            (dated if match else undated).append(match.group(1) if match else heading)
        # Four legacy entries predate the dated-heading convention; a new entry may not
        # join them, so the count is pinned rather than allowed to grow.
        self.assertEqual(len(undated), 4, f'an entry heading is not `## YYYY-MM-DD — subject`: {undated}')
        self.assertEqual(dated, sorted(dated, reverse=True), 'the dated entries are not newest first')

    def test_every_changes_paragraph_sits_under_its_own_heading(self):
        lines = CHANGELOG.read_text(encoding='utf-8').splitlines()
        open_entry = None
        for number, line in enumerate(lines, start=1):
            if line.startswith('## '):
                open_entry = line
            elif line.startswith('**Changes:**'):
                with self.subTest(line=number):
                    self.assertIsNotNone(open_entry,
                                         'a **Changes:** paragraph has no entry heading above it')
                    self.assertNotIn('**Changes:**', open_entry)
                # One body per heading: a second **Changes:** before the next heading means
                # a heading was lost between them.
                open_entry = None
