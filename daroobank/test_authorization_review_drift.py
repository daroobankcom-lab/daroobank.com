"""The authorization review document must agree with the code it describes.

`docs/AUTHORIZATION_REVIEW.md` carries two generated tables — every staff route the
resolver serves, and every non-staff route — derived by
`daroobank/authorization_review.py` from the live URL resolver and from the pinned staff
suites. This suite re-renders them and compares, so the review cannot drift into a
document that describes routes that no longer exist, requirements that were changed
elsewhere, or ADRs that were never written.

It also pins the honest parts: that the document states what it does not establish, and
that the sign-off table is empty rather than filled in with an invented owner or date.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase
from django.urls import get_resolver

from .authorization_review import (AUTH_ORDER, BEGIN, END, generated_block, public_rows, render_review,
                                   staff_rows)
from .test_staff_method_sweep import EXPECTED_ALLOW

ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / 'docs' / 'AUTHORIZATION_REVIEW.md'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
HEADINGS = re.compile(r'\A(#{2,3}) ')


def cells(line):
    return [cell.strip() for cell in line.strip().strip('|').split('|')]


def plain(cell):
    """A cell renders code in backticks; the derived rows carry the bare value."""
    match = re.fullmatch(r'`([^`]*)`', cell)
    return match.group(1) if match else cell


def document():
    return REVIEW.read_text(encoding='utf-8')


def table(document, heading):
    """Return the cell lists of the first markdown table under a heading."""
    lines = document.splitlines()
    start = lines.index(heading)
    rows = []
    seen_header = False
    for line in lines[start + 1:]:
        if HEADINGS.match(line):
            break
        if not line.startswith('|'):
            if seen_header:
                break
            continue
        if set(line.replace('|', '').strip()) <= {'-', ' ', ':'}:
            seen_header = True
            continue
        if seen_header:
            rows.append(cells(line))
    return rows


def named_rows(document, heading):
    """Map the first column of a table (a route name in backticks) to its cells."""
    rows = table(document, heading)
    named = {}
    for row in rows:
        match = re.fullmatch(r'`([^`]+)`', row[0])
        assert match is not None, f'unexpected first cell in {heading}: {row[0]!r}'
        named[match.group(1)] = row
    return named


class AuthorizationReviewDriftTests(SimpleTestCase):
    def test_the_generated_block_matches_a_fresh_render(self):
        text = document()
        self.assertEqual(text.count(BEGIN), 1, 'the generated block must be delimited exactly once')
        self.assertEqual(text.count(END), 1)
        self.assertLess(text.index(BEGIN), text.index(END))
        self.assertEqual(generated_block(text), render_review(),
                         'docs/AUTHORIZATION_REVIEW.md drifted; re-run the generator in its header.')

    def test_the_header_counts_match_the_resolver(self):
        staff = {pattern.name for pattern in get_resolver().url_patterns if pattern.name.startswith('staff_')}
        public = {pattern.name for pattern in get_resolver().url_patterns if not pattern.name.startswith('staff_')}
        block = generated_block(document())
        header = block.splitlines()[1]
        self.assertIn(f'**{len(staff)} staff routes**', header)
        self.assertIn(f'**{len(public)} non-staff routes**', header)
        self.assertEqual(len(list(staff_rows())), len(staff))
        self.assertEqual(len(list(public_rows())), len(public))

    def test_the_generated_block_is_stable_across_interpreters(self):
        # `AUTH_ROUTES` is a frozenset, whose iteration order follows the hash seed. Two
        # renders in one process are not enough to prove the document is reproducible, so
        # pin the ordering directly and pin it against the canonical set.
        from .test_staff_authorization_matrix import AUTH_ROUTES
        self.assertEqual(set(AUTH_ORDER), set(AUTH_ROUTES), 'the authentication endpoints changed')
        self.assertEqual(len(AUTH_ORDER), 2)
        names = [row['name'] for row in staff_rows()]
        self.assertEqual(names[-2:], list(AUTH_ORDER))
        self.assertEqual(render_review(), render_review())

    def test_the_requirement_shapes_are_counted(self):
        # The ADR quotes these counts; pinning them here keeps the document honest and
        # makes a changed requirement shape a deliberate edit in two places.
        rows = list(staff_rows())
        shapes = {'all': 0, 'any': 0, 'staff-only': 0, 'prose': 0}
        for row in rows:
            requirement = row['requirement']
            if requirement.startswith('all of'):
                shapes['all'] += 1
            elif requirement.startswith('any of'):
                shapes['any'] += 1
            elif 'no specific permission' in requirement:
                shapes['staff-only'] += 1
            else:
                shapes['prose'] += 1
        self.assertEqual(shapes, {'all': 36, 'any': 4, 'staff-only': 1, 'prose': 2})
        self.assertEqual(sum(shapes.values()), len(rows))
        self.assertEqual(sum(row['writes'].startswith('yes') for row in rows), 14)
        self.assertEqual(sum(row['writes'].startswith('no') for row in rows), 29)

    def test_the_staff_table_covers_exactly_the_resolver(self):
        block = generated_block(document())
        rows = named_rows(block, '## Staff routes')
        live = {pattern.name for pattern in get_resolver().url_patterns if pattern.name.startswith('staff_')}
        self.assertEqual(set(rows) - live, set(), 'the review lists routes the resolver does not serve')
        self.assertEqual(live - set(rows), set(), 'the resolver serves routes the review omits')
        # The same coverage, asserted on the derived rows rather than on the document.
        self.assertEqual({row['name'] for row in staff_rows()}, live)

    def test_every_staff_row_states_methods_requirement_pattern_and_writes(self):
        rows = named_rows(generated_block(document()), '## Staff routes')
        declared = {row['name']: row for row in staff_rows()}
        for name, row in sorted(rows.items()):
            with self.subTest(route=name):
                _route, pattern, methods, requirement, writes, evidence = row
                self.assertNotEqual((pattern, methods, requirement, writes, evidence),
                                    ('', '', '', '', ''), 'an empty cell is not an inventory')
                self.assertEqual(plain(pattern), declared[name]['pattern'])
                self.assertEqual(plain(methods), declared[name]['methods'])
                self.assertIn(plain(methods), set(EXPECTED_ALLOW.values()),
                              'the methods column names a method set no suite pins')
                self.assertEqual(requirement, declared[name]['requirement'])
                self.assertEqual(writes, declared[name]['writes'])
                self.assertEqual(evidence, declared[name]['evidence'])
                self.assertTrue(writes.startswith('yes —') or writes.startswith('no —'),
                                'the writes column must classify the route')

    def test_the_non_staff_table_covers_exactly_the_resolver(self):
        block = generated_block(document())
        rows = named_rows(block, '## Non-staff routes')
        live = {pattern.name for pattern in get_resolver().url_patterns if not pattern.name.startswith('staff_')}
        self.assertEqual(set(rows), live)
        probes = sum(int(row[2]) for row in rows.values())
        from .test_public_route_privacy_matrix import PUBLIC_ROUTES
        self.assertEqual(probes, len(PUBLIC_ROUTES), 'every public probe row must be accounted for')
        for name, row in sorted(rows.items()):
            with self.subTest(route=name):
                self.assertNotEqual(plain(row[1]), '', 'the pattern column must not be empty')
                self.assertTrue(int(row[2]) >= 1, 'a public route with no probe is not covered')
                self.assertRegex(row[3], r'\A\d{3}(, \d{3})*\Z', 'statuses must be literal status codes')

    def test_the_evidence_column_cites_adr_documents_that_exist(self):
        cited = set()
        for row in staff_rows():
            cited |= set(re.findall(r'\b0\d{3}\b', row['evidence']))
        for row in public_rows():
            cited |= set(re.findall(r'\b0\d{3}\b', row['evidence']))
        self.assertGreaterEqual(len(cited), 10, 'the review should cite the suites it rests on')
        missing = sorted(number for number in cited
                         if not list(ADR_DIR.glob(f'{number}-*.md')))
        self.assertEqual(missing, [], 'the review cites ADR numbers with no document')
        self.assertIn('0200', cited)
        self.assertIn('0213', cited)

    def test_the_writes_column_names_modules_that_actually_cover_the_route(self):
        for row in staff_rows():
            if not row['writes'].startswith('yes'):
                continue
            with self.subTest(route=row['name']):
                relative = re.search(r'`([^`]+\.py)`', row['writes']).group(1)
                source = (ROOT / relative).read_text(encoding='utf-8')
                self.assertIn(row['name'], source, f'{relative} no longer references {row["name"]}')
                self.assertIn('invalidate_and_reactivate', source,
                              f'{relative} no longer parks a write around a password invalidation')

    def test_the_document_states_what_it_does_not_establish(self):
        text = document()
        for phrase in ('not an approval', 'not a threat model', 'no MFA', 'DEBUG-only',
                       'dormant-session residual', 'does not establish', 'Sign-off',
                       'runs to completion', 'synthetic', 'fabrication'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, 'the review dropped a statement of its own limits')

    def test_the_sign_off_table_is_empty_rather_than_invented(self):
        text = document()
        rows = table(text, '## Questions that need an owner')
        self.assertGreaterEqual(len(rows), 6, 'the questions needing an owner were dropped')
        for row in rows:
            with self.subTest(question=row[0][:40]):
                self.assertEqual(len(row), 4, 'each question needs owner, date and answer columns')
                self.assertTrue(row[0], 'a question must not be blank')
                self.assertEqual((row[1], row[2], row[3]), ('', '', ''),
                                 'owners and dates must not be invented here; the project assigns them')

    def test_the_review_is_linked_from_the_evidence_checklist(self):
        evidence = (ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md').read_text(encoding='utf-8')
        self.assertIn('AUTHORIZATION_REVIEW.md', evidence,
                      'the Phase 1 checklist must point at the review it asks for')
