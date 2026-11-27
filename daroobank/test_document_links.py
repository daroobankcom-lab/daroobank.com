"""The documentation graph holds together: every link, anchor, index entry and named suite resolves.

This repository documents itself heavily — 258 markdown files, of which 229 are numbered decision
records, cross-linked to each other, to the guides and to the test suites that measure them. A
broken link in that graph is invisible until a reader follows it, and the failure mode is quiet:
a decision record that cites a suite which was renamed, an index that forgets the newest record,
a section anchor that stopped matching after a heading was reworded.

The checks here are the ones that can be decided mechanically. Links and anchors are resolved
against the files themselves, the decision-record index is held to the directory it indexes, the
record numbers are held to be contiguous and unique, every suite a record names must exist, and
no document may be orphaned — unreachable from every other document, which is how a file survives
after the thing it described is deleted.

Text inside fenced code blocks is not prose: a shell comment is not a heading and an example path
is not a link, so both are skipped. What is *not* checked is whether a linked document says
something true, whether a summary in the index still matches the record it points at, or whether
the right document was linked rather than a plausible one.
"""
import re
import unicodedata
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
ADR_INDEX = ADR_DIR / 'README.md'
FENCE = re.compile(r'^(```|~~~)')
HEADING = re.compile(r'^(#{1,6})\s+(.*)$')
LINK = re.compile(r'\[[^\]]*\]\(\s*([^)\s]+)\s*\)')
EXTERNAL = ('http://', 'https://', 'mailto:')
SUITE_LINE = re.compile(r'^Suite:\s*(.*)$')
MODULE = re.compile(r'`([^`]+\.py)`')
# Measured, so that a scan which silently finds nothing cannot pass.
DOCUMENT_COUNT = 269
ADR_COUNT = 235
LINK_COUNT = 1157
EXTERNAL_COUNT = 31
ANCHOR_COUNT = 29
SUITE_LINE_COUNT = 25


def documents():
    """Every markdown document in the repository, README first."""
    return [ROOT / 'README.md'] + sorted((ROOT / 'docs').rglob('*.md'))


def prose(text):
    """The lines of a document that are not inside a fenced code block."""
    lines, inside = [], False
    for line in text.splitlines():
        if FENCE.match(line.strip()):
            inside = not inside
            continue
        if not inside:
            lines.append(line)
    return lines


def headings(text):
    return [(len(match.group(1)), match.group(2)) for match in
            (HEADING.match(line) for line in prose(text)) if match]


def all_links(text):
    found = []
    for line in prose(text):
        found += LINK.findall(line)
    return found


def slug(heading_text):
    """GitHub's anchor slug: lowercase, letters and numbers kept, spaces to hyphens."""
    text = heading_text.strip().lower().replace('`', '')
    kept = [character for character in text
            if character.isalnum() or character in '-_ '
            or unicodedata.category(character).startswith('L')]
    return ''.join(kept).replace(' ', '-')


class DocumentSetTests(SimpleTestCase):
    def test_the_document_set_is_pinned(self):
        found = documents()
        self.assertEqual(len(found), DOCUMENT_COUNT)
        self.assertGreater(len(found), 200, 'the scan found almost nothing, so the rest proves nothing')
        for document in found:
            with self.subTest(document=str(document.relative_to(ROOT))):
                lines = document.read_text(encoding='utf-8').splitlines()
                self.assertTrue(lines and lines[0].startswith('# '),
                                'a document does not open with a single top-level heading')
                self.assertEqual([level for level, _text in headings(document.read_text(encoding='utf-8'))
                                  if level == 1].count(1), 1,
                                'a document has more than one top-level heading')

    def test_decision_record_numbers_are_contiguous_and_unique(self):
        records = sorted(ADR_DIR.glob('[0-9][0-9][0-9][0-9]-*.md'))
        self.assertEqual(len(records), ADR_COUNT)
        numbers = [int(record.name[:4]) for record in records]
        self.assertEqual(len(set(numbers)), len(numbers), 'two decision records share a number')
        self.assertEqual(numbers, list(range(1, ADR_COUNT + 1)),
                         'a decision record number is missing, so a record was deleted rather than superseded')

    def test_no_document_is_orphaned(self):
        found = documents()
        reachable = set()
        for document in found:
            for target in all_links(document.read_text(encoding='utf-8')):
                if target.startswith(EXTERNAL):
                    continue
                path_part = target.partition('#')[0]
                if path_part:
                    reachable.add((document.parent / path_part).resolve())
        orphans = sorted(str(document.relative_to(ROOT)) for document in found
                         if document.name != 'README.md' and document.resolve() not in reachable)
        self.assertEqual(orphans, [], 'a document no other document links to')


class LinkResolutionTests(SimpleTestCase):
    def test_every_relative_link_resolves_to_a_file(self):
        total = external = 0
        for document in documents():
            for target in all_links(document.read_text(encoding='utf-8')):
                total += 1
                if target.startswith(EXTERNAL):
                    external += 1
                    continue
                path_part = target.partition('#')[0]
                if not path_part:
                    continue
                with self.subTest(document=str(document.relative_to(ROOT)), target=target):
                    self.assertTrue((document.parent / path_part).is_file(),
                                    'a link points at a file that does not exist')
        self.assertEqual(total, LINK_COUNT)
        self.assertEqual(external, EXTERNAL_COUNT)

    def test_every_anchor_resolves_to_a_heading_in_its_target(self):
        checked = 0
        slugs = {document.resolve(): {slug(text) for _level, text in headings(document.read_text(encoding='utf-8'))}
                 for document in documents()}
        for document in documents():
            for target in all_links(document.read_text(encoding='utf-8')):
                if target.startswith(EXTERNAL):
                    continue
                path_part, _, anchor = target.partition('#')
                if not anchor:
                    continue
                checked += 1
                resolved = (document.parent / path_part).resolve() if path_part else document.resolve()
                with self.subTest(document=str(document.relative_to(ROOT)), target=target):
                    self.assertIn(resolved, slugs, 'an anchor points into a file this scan does not read')
                    self.assertTrue(anchor in slugs[resolved] or slug(anchor) in slugs[resolved],
                                    'an anchor no longer matches any heading in its target')
        self.assertEqual(checked, ANCHOR_COUNT)


class DecisionRecordIndexTests(SimpleTestCase):
    def test_every_decision_record_is_listed_in_the_index(self):
        index = ADR_INDEX.read_text(encoding='utf-8')
        for record in sorted(ADR_DIR.glob('[0-9][0-9][0-9][0-9]-*.md')):
            with self.subTest(record=record.name):
                self.assertIn(record.name, index,
                              'a decision record is not listed in the index that is supposed to list it')
        for target in all_links(index):
            if target.startswith(EXTERNAL):
                continue
            path_part = target.partition('#')[0]
            if path_part:
                with self.subTest(target=target):
                    self.assertTrue((ADR_INDEX.parent / path_part).is_file())

    def test_every_suite_a_decision_record_names_exists(self):
        lines = 0
        for record in sorted(ADR_DIR.glob('[0-9][0-9][0-9][0-9]-*.md')):
            for line in prose(record.read_text(encoding='utf-8')):
                match = SUITE_LINE.match(line)
                if not match:
                    continue
                lines += 1
                for module in MODULE.findall(match.group(1)):
                    with self.subTest(record=record.name, module=module):
                        self.assertTrue((ROOT / module).is_file(),
                                        'a decision record names a suite that does not exist')
        self.assertEqual(lines, SUITE_LINE_COUNT,
                         'the number of decision records that name a suite changed')
        self.assertGreater(lines, 0)
