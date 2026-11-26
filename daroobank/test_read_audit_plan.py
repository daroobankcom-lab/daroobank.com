"""The read-audit plan is a proposal, its cost is measured, and nothing is implemented.

ADR 0221 recorded that no component of this application records that a read happened, and
deliberately did not add logging: an access log is a decision about retention, reader identity and
tamper-resistance that the project had not made. `docs/READ_AUDIT_PLAN.md` is that decision written
down — what a read audit has to satisfy here, which six decisions block it, what the
in-application option costs in pins that would have to move, and which alternatives exist.

These tests hold the plan to three properties. It has to stay a proposal: nothing may be
implemented while it claims nothing is. It has to cite the requirements it is written against, so
the plan cannot drift away from `docs/SECURITY.md`, the settings comment that keeps the staff
portal development-only and the record that measured the absence. And its cost has to be the
measured one: the suites it names must exist, the failures must add up, and the schema numbers
must be the ones the reverted prototype produced.

Phrases are compared after collapsing whitespace, because the plan is hard-wrapped and a sentence
crosses lines. What is not checked is whether the plan is the right plan: whether reads should be
recorded at all, what may identify a reader, how long entries are kept and how they are protected
from the application's own database role are decisions for named owners, and no test can make them.
"""
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'READ_AUDIT_PLAN.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
THROTTLE = ROOT / 'staff_security' / 'throttle.py'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
ADR_0221 = ADR_DIR / '0221-no-read-audit.md'
CASCADE_ROW = re.compile(r'^\| `([\w/.]+\.py)` \(ADR (\d{4})\) \| (\d+) \|', re.M)
RECORD_LIKE = ('access', 'audit', 'event', 'log', 'track', 'visit')
PROJECT_APPS = ('catalog', 'clinical', 'ingestion', 'pricing', 'sources', 'staff_security')
DECISIONS = ['Scope', 'Identity and privacy', 'Retention', 'Tamper-resistance', 'Where it lives',
             'Enablement']
# The prototype that was built and reverted, measured on a freshly migrated throwaway database.
PROTOTYPE_SCHEMA = {'tables': 33, 'columns': 283, 'indexes': 113, 'constraints': 139,
                    'foreign keys': 51, 'applied migrations': 32}
CURRENT_SCHEMA = {'tables': 32, 'columns': 276, 'indexes': 108, 'constraints': 136,
                  'foreign keys': 50, 'applied': 31}
SUPERSEDED = ('0216', '0217', '0220', '0221', '0222', '0223', '0225')


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


def section(text, heading):
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def camel_words(name):
    return [word.lower() for word in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)', name)]


class PlanStructureTests(SimpleTestCase):
    def test_the_plan_is_a_proposal_with_six_blocking_decisions(self):
        text = read(PLAN)
        self.assertTrue(text.startswith('# '), 'the plan does not open with a single top heading')
        plan = flat(text)
        self.assertIn('This document is a **proposal**, not an implemented or approved control', plan)
        self.assertIn('Nothing in this application records that a read happened', plan)
        for heading in ('What a read audit has to satisfy here',
                        'Decisions required before implementation',
                        'Measured cost of the in-application option',
                        'Alternatives',
                        'Verification before any enablement'):
            self.assertIn(heading, sections(text), 'a required section is missing')
        self.assertEqual(re.findall(r'^\d+\. \*\*(.+?)\.\*\*',
                                    section(text, 'Decisions required before implementation'), re.M),
                         DECISIONS)
        self.assertGreaterEqual(len(re.findall(r'^- ', section(text, 'Verification before any enablement'),
                                               re.M)), 6)

    def test_the_plan_cites_the_requirements_it_is_written_against(self):
        plan = flat(read(PLAN))
        security = flat(read(SECURITY))
        for fragment in ('actor, role, target, before/after versions or hashes, decision, time and '
                         'request correlation', 'without PHI in general logs',
                         'from modification by application roles'):
            self.assertIn(fragment, security, 'SECURITY.md no longer asks for this')
            self.assertIn(fragment, plan, 'the plan stopped quoting the requirement it answers')
        self.assertIn('data minimization', plan)
        self.assertIn('legal review', plan)
        comment = '# The staff portal is restricted to development until MFA, throttling and audit exist.'
        self.assertIn(comment, read(SETTINGS))
        self.assertIn('until MFA, throttling and audit exist', plan)
        self.assertTrue(ADR_0221.is_file(), 'the record that measured the absence is missing')
        self.assertIn('0221-no-read-audit.md', plan)
        self.assertIn('salted_hmac', read(THROTTLE))
        self.assertIn('staff_security/throttle.py', plan)
        self.assertIn('not a raw IP or account identifier', flat(read(ROOT / 'staff_security' / 'models.py')))
        # The edge alternative is the one ADR 0223 wrote into the deployment guide.
        self.assertIn('Abuse protection is external', read(DEPLOYMENT))
        self.assertIn('assigns abuse protection to the edge', plan)


class MeasuredCostTests(SimpleTestCase):
    def test_the_cascade_table_names_suites_that_exist_and_counts_that_add_up(self):
        text = read(PLAN)
        table = section(text, 'Measured cost of the in-application option')
        rows = CASCADE_ROW.findall(table)
        self.assertEqual(len(rows), 7, 'the cascade table no longer names seven suites')
        for path, record, _count in rows:
            with self.subTest(suite=path):
                self.assertTrue((ROOT / path).is_file(), 'the plan names a suite that does not exist')
                self.assertTrue(list(ADR_DIR.glob(f'{record}-*.md')), f'ADR {record} does not exist')
        self.assertEqual(sorted(int(count) for _path, _record, count in rows), [1, 1, 1, 3, 4, 5, 5])
        self.assertEqual(sum(int(count) for _path, _record, count in rows), 20)
        self.assertIn('— 138 tests —', flat(table))
        self.assertIn('20 failures across 7 of them', flat(text))
        self.assertIn('built and reverted', flat(text))

    def test_the_prototype_schema_numbers_are_the_measured_ones(self):
        sentence = flat(section(read(PLAN), 'Measured cost of the in-application option'))
        self.assertIn('33 tables, 283 columns, 113 indexes, 139 constraints, 51 foreign keys and '
                      '32 applied migrations', sentence)
        self.assertIn("against today's 32, 276, 108, 136, 50 and 31", sentence)
        for label, value in PROTOTYPE_SCHEMA.items():
            self.assertIn(f'{value} {label}', sentence, f'the prototype {label} count moved')
        for label, value in CURRENT_SCHEMA.items():
            self.assertIn(str(value), sentence, f"today's {label} count is no longer compared")
        self.assertIn('no_selected_issues', sentence)

    def test_the_records_the_plan_would_supersede_are_named_and_exist(self):
        text = read(PLAN)
        closing = flat(section(text, 'Verification before any enablement'))
        for record in SUPERSEDED:
            with self.subTest(record=record):
                self.assertTrue(list(ADR_DIR.glob(f'{record}-*.md')), f'ADR {record} does not exist')
                self.assertIn(record, closing, 'the verification list stopped naming a record')


class NothingImplementedTests(SimpleTestCase):
    def test_no_read_audit_exists_while_the_plan_says_so(self):
        self.assertFalse((ROOT / 'daroobank' / 'read_audit.py').exists(),
                         'a read-audit module exists while the plan says nothing is implemented')
        self.assertNotIn('READ_AUDIT', read(SETTINGS))
        self.assertEqual(len(settings.MIDDLEWARE), 13)
        for entry in settings.MIDDLEWARE:
            for token in RECORD_LIKE:
                self.assertNotIn(token, camel_words(entry.rsplit('.', 1)[-1]),
                                 f'{entry} is named like an access record')
        project_models = [model for model in apps.get_models() if model._meta.app_label in PROJECT_APPS]
        self.assertEqual(len(project_models), 24, 'the project model count changed')
        self.assertEqual([model.__name__ for model in project_models
                          if any(token in camel_words(model.__name__) for token in RECORD_LIKE)], [],
                         'a project model is named like an access record')
