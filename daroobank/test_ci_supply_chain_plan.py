"""What the CI and supply-chain plan claims, and whether the tree still measures that.

`docs/PHASE1_RELEASE_EVIDENCE.md` opens the CI and supply-chain row with the requirement list
this plan prices against — independent review, immutable production artifacts and image digests,
OS/transitive dependency review, staging/release gates and rollback — and records what a run
produces: no artifact, no exports, no waiting job, no protected environment, four mutable
base-image references and one development image destroyed inside the run. `docs/DEPLOYMENT.md`
states the release gate itself. This suite pins `docs/CI_SUPPLY_CHAIN_PLAN.md` to the files CI
decides from and to a completed run's recorded numbers.

It recounts the workflow's shape from `.github/workflows/checks.yml` (2 jobs, 22 steps, 17 run
steps, 5 SHA-pinned uses references, one contents:read permission, zero environment keys, zero
needs, zero exports), the locks from the three requirement files, and the absences as counts
over the CI-deciding files; it requires each requirement quote to exist both in the plan and in
its source document; and it requires the plan to keep saying it proposes and implements
nothing — no workflow line, dependency, environment key, action or tool.

Parsing is textual, like `daroobank/test_ci_artifact_gate.py`: the runtime lock is exact and
deliberately carries no YAML library, and every measurement here is a count a regular expression
decides without ambiguity. What this suite cannot tell is whether a gate that does not exist
here exists elsewhere — a registry, an external pipeline, a manual approval — or whether the
eight decisions should be answered at all.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'CI_SUPPLY_CHAIN_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0237-ci-supply-chain-plan.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
GUIDE = ROOT / 'docs' / 'DEVELOPMENT_GUIDE.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
DOCKERFILE = ROOT / 'Dockerfile'
COMPOSE = ROOT / 'compose.yaml'
REQUIREMENTS = ROOT / 'requirements.txt'
REQUIREMENTS_BUILD = ROOT / 'requirements-build.txt'
PACKAGE_LOCK = ROOT / 'tests' / 'browser' / 'package-lock.json'

SECTIONS = ['What is true today, measured', 'Requirements',
            'Candidate approach and decisions required', 'Options and what each costs',
            'Required behavior before any release gate', 'Verification before any enablement']
SUBSECTIONS = ["The workflow's shape", 'What one run produces', 'The locks and their audits',
               'What a later gate could read', 'What does not exist, as counts']
DECISIONS = [
    'What artifact, if any, would a release gate promote, and who approves a promotion?',
    'Which of the four base-image references become digest-pinned, who refreshes the digests, '
    'and how is the `docker run` wrapper at `checks.yml` line 80 kept in step with the service '
    'image at line 13?',
    'What SBOM is generated, for which scope (the two Python locks, the npm tree, the built '
    'image, all three), with which tool, stored where, and who reviews it?',
    'What is signed, with which key material, who verifies the signature before a deploy, and '
    'what happens when verification fails?',
    'How are OS and transitive dependencies reviewed, and on what cadence?',
    'What is the staging/release gate topology — which environment names, which required '
    'reviewers, which `needs:` edges, and which value does the gate read?',
    'What does rollback mean here — previous image digest, previous commit, or database '
    'migrations reversed — who triggers it, and when was it rehearsed?',
    'What does "independent review" cover — every workflow change, every release, every digest '
    'bump — who counts as independent, and where is the review recorded?',
]
OPTIONS = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'must not be read as a decision',
                    'the temporary probe that collected them has been deleted',
                    'no new workflow, no new environment variable']
FORBIDDEN_SELECTION = ['The selected approach is to', 'is selected because',
                       'the recommended approach', 'should be adopted',
                       'The selected option is']
# The requirement sentences, each pinned in the plan and in the document that states it.
QUOTED_REQUIREMENTS = [
    (EVIDENCE, 'independent review, immutable production artifacts and image digests, '
               'OS/transitive dependency review, staging/release gates and rollback'),
    (EVIDENCE, 'CI produces no artifact at all: nothing is uploaded, tagged, pushed, described '
               'by an SBOM or signed, no step exports a value a later gate could read, no job '
               'waits on another or runs in a protected environment'),
    (EVIDENCE, 'all four base-image references (`postgres:16` three times, '
               '`python:3.11-slim` once) are mutable tags rather than digests, so the same '
               'commit can build a different image'),
    (EVIDENCE, 'The only image the repository can build is a development image — untagged, '
               'root-owned, serving through `runserver`, destroyed inside the run'),
    (EVIDENCE, 'CI success is not a security certification'),
    (EVIDENCE, 'pins all five action references to 40-character commit SHAs with their '
               'versions commented'),
    (EVIDENCE, 'installs both hash-pinned lock files with `--require-hashes` behind a negative '
               'control that requires pip to reject a zeroed hash'),
    (EVIDENCE, 'audits the resolved dependencies and the built image with `pip-audit --strict`'),
    (DEPLOYMENT, 'Pin and scan dependencies and base images, generate SBOM where practical, '
                 'run tests/migrations on staging and validate rollback compatibility'),
    (ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0226-ci-artifact-gate.md',
     'outputs annotations and temporary files and nothing else'),
]
# Numbers the plan states; each must survive as a flat substring of it.
MEASURED = [
    '217 lines',
    '2 jobs, 22 steps, 17 `run:` steps and 5 `uses:` references',
    '40-character commit SHA with a version comment',
    'Exactly one top-level permission: `contents: read`',
    'one `if:` condition in the file — `if: always()`',
    'both jobs carry `timeout-minutes: 15`',
    '0 `environment:` keys on any job and 0 `needs:` edges',
    '0 `GITHUB_OUTPUT`, 0 `GITHUB_ENV` and 1 `GITHUB_PATH`',
    '10 `::error::` annotations and refers to `RUNNER_TEMP` 35 times',
    '2026-11-27T13:04:57Z',
    '2026-11-27T13:17:24Z',
    '12m27s',
    'The `django` job ran 740 s',
    'The `compose` job ran 69 s',
    '9m22s',
    'writes 14 files into the workspace',
    'requirements.txt` is 94 lines: 7 exact pins and 78 `--hash=sha256:` lines',
    '298 lines with 22 `sha512-` integrity entries',
    '`THESE PACKAGES DO NOT MATCH THE HASHES`',
    'checked 7 releases',
    'checked 2 releases',
    'No known vulnerabilities found',
    'found 0 vulnerabilities',
    '4 base-image references and 0 digests',
    'a `total_count` of 0',
    'exactly 1 file',
    'exit code 1',
    '`sbom` 0, `syft` 0, `cyclonedx` 0',
]
DEPENDENT_SUITES = ('daroobank/test_ci_artifact_gate.py',
                    'daroobank/test_backup_recovery_plan.py',
                    'daroobank/test_environment_documentation.py',
                    'daroobank/test_mfa_implementation_plan.py',
                    'daroobank/test_network_tls_plan.py',
                    'daroobank/test_document_links.py',
                    'daroobank/test_release_notes_structure.py',
                    'daroobank/test_secret_rotation_plan.py')
TOOLS = ('__init__.py', 'browser_test_diagnostics.py', 'check_lock_metadata.py',
         'report_synthetic_test_failures.py', 'verify_runtime_lock.py', 'wait_for_database.py')
# Tokens whose zero-occurrence in the CI-deciding files is the measured absence.
ABSENT_TOKENS = ('sbom', 'syft', 'cyclonedx', 'cosign', 'sigstore', 'attest', '@sha256:',
                 'retention-days', 'id-token', 'ghcr', 'buildx', 'docker push', 'docker tag',
                 'upload-artifact', 'download-artifact', 'GITHUB_OUTPUT', 'GITHUB_ENV')
BASE_IMAGES = {('.github/workflows/checks.yml', 13): 'postgres:16',
               ('.github/workflows/checks.yml', 80): 'postgres:16',
               ('compose.yaml', 6): 'postgres:16',
               ('Dockerfile', 2): 'python:3.11-slim'}


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def section(text, heading):
    match = re.search(rf'^## {re.escape(heading)}$(.*?)(?=^## |\Z)', text, re.M | re.S)
    assert match, f'section missing: {heading}'
    return match.group(1)


def ci_files():
    return [WORKFLOW, DOCKERFILE, COMPOSE, *sorted((ROOT / 'tools').glob('*.py'))]


class PlanStructureTests(SimpleTestCase):
    def test_the_plan_states_its_own_shape(self):
        text = read(PLAN)
        self.assertTrue(text.startswith('# '), 'the plan does not open with a single top heading')
        headings = re.findall(r'^## (.+)$', text, re.M)
        self.assertEqual(headings, SECTIONS, 'the plan gained or lost a section')
        self.assertEqual(re.findall(r'^### (.+)$', text, re.M), SUBSECTIONS,
                         'the measured subsections moved')
        decisions = flat(section(text, 'Candidate approach and decisions required'))
        found = re.findall(r'\d+\. \*\*(.+?)\*\*', decisions)
        self.assertEqual(found, DECISIONS, 'the decisions the plan leaves open changed')
        options = section(text, 'Options and what each costs')
        self.assertEqual(re.findall(r'^\| \*\*([A-G])\.', options, re.M), OPTIONS,
                         'the option table lost or gained a letter')
        long_lines = [(number, len(line)) for number, line in enumerate(text.splitlines(), 1)
                      if len(line) > 105 and not line.startswith('|')]
        self.assertEqual(long_lines, [], 'a prose line exceeds 105 characters')

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        flat_plan = flat(read(PLAN))
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan,
                              'the plan stopped saying that it proposes and implements nothing')
        for phrase in FORBIDDEN_SELECTION:
            with self.subTest(forbidden=phrase):
                self.assertNotIn(phrase, flat_plan,
                                 'the plan selected an approach instead of pricing it')
        for name in DEPENDENT_SUITES:
            self.assertIn(name, flat_plan, f'the plan does not name {name}')
        for name in ('CI_SUPPLY_CHAIN_PLAN.md', '0237-ci-supply-chain-plan.md',
                     '0226-ci-artifact-gate.md'):
            self.assertIn(name, flat_plan)

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        flat_plan = flat(read(PLAN))
        for source, quote in QUOTED_REQUIREMENTS:
            with self.subTest(source=source.name):
                self.assertIn(quote, flat_plan,
                              'the plan dropped a requirement it is priced against')
                self.assertIn(quote, flat(read(source)),
                              f'{source.name} no longer states a sentence the plan quotes')

    def test_the_plan_states_the_measured_numbers(self):
        flat_plan = flat(read(PLAN))
        for number in MEASURED:
            with self.subTest(number=number):
                self.assertIn(number, flat_plan,
                              'the plan stopped stating a measured number')


class WorkflowRecountTests(SimpleTestCase):
    def test_the_workflow_shape_is_recounted_from_the_file(self):
        text = read(WORKFLOW)
        self.assertEqual(re.search(r'^name: (.*)$', text, re.M).group(1), 'Development checks')
        block = text.split('\npermissions:')[0].partition('\non:\n')[2]
        self.assertEqual(re.findall(r'^  ([\w-]+):', block, re.M), ['push', 'pull_request'])
        self.assertEqual(re.findall(r'^  ([a-z][\w-]*):\n    runs-on:', text, re.M),
                         ['django', 'compose'])
        self.assertEqual(len(re.findall(r'^      - (?:name|uses|run|if):', text, re.M)), 22)
        self.assertEqual(len(re.findall(r'^        run: ', text, re.M)), 17)
        uses = re.findall(r'^      - uses: (\S+)', text, re.M)
        self.assertEqual(len(uses), 5)
        shas = [uses_line.split('@')[1] for uses_line in uses]
        self.assertEqual([len(sha) for sha in shas], [40, 40, 40, 40, 40])
        for sha in shas:
            self.assertRegex(sha, r'^[0-9a-f]{40}$')
        self.assertEqual(re.findall(r'^      - uses: ([^@\s]+)@', text, re.M).count(
            'actions/checkout'), 2)
        permissions = re.search(r'^permissions:\n((?:  [^\n]*\n)+)', text, re.M).group(1)
        self.assertEqual(permissions.strip().splitlines(), ['contents: read'])
        self.assertEqual(len(re.findall(r'^    permissions:', text, re.M)), 0)
        self.assertEqual(re.findall(r'timeout-minutes: (\d+)', text, re.M), ['15', '15'])
        self.assertEqual(re.findall(r'^\s+if: (.*)$', text, re.M), ['always()'])
        self.assertEqual(len(re.findall(r'^\s+environment:', text, re.M)), 0)
        self.assertEqual(len(re.findall(r'^\s+needs:', text, re.M)), 0)
        self.assertEqual(text.count('GITHUB_OUTPUT'), 0)
        self.assertEqual(text.count('GITHUB_ENV'), 0)
        self.assertEqual(text.count('GITHUB_PATH'), 1)
        self.assertEqual(text.count('RUNNER_TEMP'), 35)
        self.assertEqual(text.count('::error::'), 10)
        self.assertEqual(text.count('persist-credentials: false'), 2)
        for token in ('release:', 'workflow_dispatch', 'schedule:', 'tags:', 'branches:'):
            self.assertNotIn(token, text.split('\npermissions:')[0])

    def test_the_locks_and_the_negative_control_are_recounted(self):
        requirements = read(REQUIREMENTS)
        build = read(REQUIREMENTS_BUILD)
        lock = read(PACKAGE_LOCK)
        workflow = read(WORKFLOW)
        self.assertEqual(len(requirements.splitlines()), 94)
        self.assertEqual(len(re.findall(r'^\S+==', requirements, re.M)), 7)
        self.assertEqual(len(re.findall(r'^    --hash=sha256:', requirements, re.M)), 78)
        self.assertEqual(re.findall(r'^([A-Za-z0-9_.\-]+)==(\S+)', build, re.M),
                         [('pip', '26.3'), ('setuptools', '84.2.1')])
        self.assertEqual(len(re.findall(r'^    --hash=sha256:', build, re.M)), 4)
        self.assertEqual(len(lock.splitlines()), 298)
        self.assertEqual(lock.count('sha512-'), 22)
        self.assertEqual(workflow.count('--require-hashes'), 2)
        self.assertEqual(read(DOCKERFILE).count('--require-hashes'), 2)
        self.assertIn('THESE PACKAGES DO NOT MATCH THE HASHES', workflow)
        self.assertIn('%064d', workflow)
        self.assertIn('pip download', workflow)
        self.assertLess(workflow.index('python -m tools.verify_runtime_lock'),
                        workflow.index('pip install --require-hashes'))
        self.assertEqual(workflow.count('check_lock_metadata'), 0,
                         'the metadata checker was wired into CI')
        self.assertEqual(workflow.count('pip-audit==2.10.1'), 2)
        self.assertEqual(workflow.count('--strict'), 2)
        self.assertEqual(workflow.count('npm audit'), 1)

    def test_the_absences_are_counts_not_memory(self):
        texts = {path: read(path).lower() for path in ci_files()}
        for token in ABSENT_TOKENS:
            for path, text in texts.items():
                with self.subTest(file=path.name, token=token):
                    self.assertNotIn(token.lower(), text,
                                     f'{path.name} gained {token}, which the plan counts absent')
        workflow = read(WORKFLOW).lower()
        for token in ('environment:', 'needs:'):
            self.assertEqual(workflow.count(token), 0)
        github_files = sorted(str(path.relative_to(ROOT))
                              for path in (ROOT / '.github').rglob('*') if path.is_file())
        self.assertEqual(github_files, ['.github/workflows/checks.yml'],
                         'a second file appeared under .github/')
        self.assertEqual((ROOT / '.github' / 'dependabot.yml').exists(), False)
        self.assertEqual(list(ROOT.glob('.github/**/renovate*')), [])
        # Each base-image reference, at its measured file and line.
        actual = {}
        for relative in ('.github/workflows/checks.yml', 'Dockerfile', 'compose.yaml'):
            for number, line in enumerate(read(ROOT / relative).splitlines(), 1):
                if 'postgres:16' in line or 'python:3.11-slim' in line:
                    actual[(relative, number)] = ('postgres:16' if 'postgres:16' in line
                                                  else 'python:3.11-slim')
        self.assertEqual(actual, BASE_IMAGES, 'the base-image references moved')
        dockerfile = read(DOCKERFILE)
        self.assertEqual(dockerfile.count('USER'), 0)
        self.assertIn('runserver', dockerfile)
        self.assertEqual(dockerfile.splitlines()[0],
                         '# Development image; not a hardened production deployment.')
        compose = read(COMPOSE)
        self.assertEqual(re.findall(r'^    build: (\S+)$', compose, re.M), ['.'])
        self.assertEqual(re.findall(r'^    image: (\S+)$', compose, re.M), ['postgres:16'],
                         'the built web service gained an image name or the db tag moved')
        self.assertEqual(read(WORKFLOW).count('docker compose down -v'), 1)
        self.assertIn('if: always()', read(WORKFLOW))


class NothingImplementedTests(SimpleTestCase):
    def test_nothing_the_plan_prices_has_been_implemented(self):
        probes = [path.name for path in (ROOT / 'daroobank').glob('test_zz*')]
        self.assertEqual(probes, [], 'a temporary probe file is still in the tree')
        self.assertEqual(sorted(path.name for path in (ROOT / 'tools').glob('*.py')), list(TOOLS),
                         'a tool appeared or disappeared beside the plan')
        self.assertEqual(list(ROOT.glob('*sbom*')) + list(ROOT.glob('.github/*sbom*')), [],
                         'an SBOM file exists')
        self.assertEqual(list(ROOT.glob('*dependabot*')) + list(ROOT.glob('*renovate*')), [],
                         'an update-bot configuration exists')
        self.assertEqual(list(ROOT.glob('*.sig')) + list(ROOT.glob('*.sigstore')), [],
                         'a signature file exists')
        workflow = read(WORKFLOW)
        self.assertEqual(workflow.count('environment:'), 0)
        self.assertEqual(workflow.count('needs:'), 0)
        self.assertEqual(workflow.count('GITHUB_OUTPUT'), 0)
        self.assertEqual(len(list((ROOT / '.github' / 'workflows').glob('*.y*ml'))), 1,
                         'a second workflow was added')

    def test_the_limiter_like_absences_stay_off_in_settings(self):
        # The plan adds no environment variable: the workflow's own env keys are unchanged
        # and the repository reads no variable this plan names.
        workflow = read(WORKFLOW)
        for variable in ('DAROOBANK_SBOM', 'DAROOBANK_SIGNING_KEY', 'DAROOBANK_RELEASE_ENV'):
            self.assertNotIn(variable, workflow)
            self.assertNotIn(variable, read(DOCKERFILE))
            self.assertNotIn(variable, read(COMPOSE))


class NeighborDocumentTests(SimpleTestCase):
    def test_the_neighbour_documents_and_the_evidence_row_link_the_plan(self):
        for path in (DEPLOYMENT, TESTING, SECURITY, RUNBOOK, GUIDE, CHANGELOG):
            text = read(path)
            with self.subTest(document=path.name):
                self.assertIn('[the CI and supply-chain plan](CI_SUPPLY_CHAIN_PLAN.md)', text,
                              f'{path.name} does not link the plan')
                self.assertIn('[ADR 0237](ARCHITECTURE_DECISIONS/0237-ci-supply-chain-plan.md)',
                              text, f'{path.name} does not link the record')
        self.assertIn('0237-ci-supply-chain-plan.md', read(INDEX),
                      'the record index does not list 0237')
        changelog = read(CHANGELOG)
        self.assertIn('## 2026-11-27 — price the CI and supply-chain gate without implementing it',
                      changelog, 'the changelog entry heading changed')
        row = [line for line in read(EVIDENCE).splitlines()
               if line.startswith('| CI and supply chain |')]
        self.assertEqual(len(row), 1, 'the CI row is missing or duplicated')
        flat_row = flat(row[0])
        for _, quote in QUOTED_REQUIREMENTS:
            if quote.startswith('Pin and scan') or quote.startswith('outputs annotations'):
                continue
            with self.subTest(quote=quote[:40]):
                self.assertIn(quote, flat_row,
                              'the evidence row dropped a gate sentence this plan quotes')
        self.assertIn('CI_SUPPLY_CHAIN_PLAN.md', flat_row)
        self.assertIn('0237-ci-supply-chain-plan.md', flat_row)
