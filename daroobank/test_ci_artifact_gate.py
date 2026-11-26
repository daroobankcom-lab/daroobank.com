"""What CI produces: verified dependencies, and no artifact at all.

`docs/DEPLOYMENT.md` lists the release gates this project has to pass before a production
release, and three of them are about artifacts: *"Pin and scan dependencies and base images,
generate SBOM where practical, run tests/migrations on staging"*, and
`docs/PHASE1_RELEASE_EVIDENCE.md` carries *"immutable production artifacts and image digests"*
plus *"staging/release gates"* as open. The suites that already exist measure the dependency half
of that sentence — `daroobank/test_lock_metadata.py` reads the lock's metadata and CI itself
rejects an incorrect artifact hash — but nothing held the workflow to the rest of it, and nothing
recorded what CI actually outputs.

This suite reads `.github/workflows/checks.yml`, `Dockerfile`, `compose.yaml`, `tools/` and the
three requirement files and pins both halves:

* what is immutable today: every action is pinned to a 40-character commit SHA with its version
  commented, checkout credentials are not persisted, both requirement files are fully hash-pinned
  and installed with `--require-hashes`, the runtime lock is verified before anything is
  installed, and a negative control proves pip rejects a wrong hash;
* what does not exist: no trigger that could produce a release, no permission that could push an
  image or attest a build, no artifact upload, no image build-and-push, no SBOM, no signature, no
  digest anywhere, no staging environment, no gate between jobs, and no value exported from one
  step for a later gate to consume. The only image this repository can build is untagged, runs as
  root, serves through `runserver`, and is destroyed inside the same run.

Parsing is textual rather than a YAML parse: the runtime lock is exact and deliberately does not
carry a YAML library, and every measurement here is a count or a shape that a regular expression
decides without ambiguity. What this suite cannot tell is whether a gate that does not exist here
exists somewhere else — a registry, an external pipeline, a manual procedure — and it does not
claim that an artifact pipeline would work if it were added.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_DIR = ROOT / '.github' / 'workflows'
WORKFLOW = WORKFLOW_DIR / 'checks.yml'
DOCKERFILE = ROOT / 'Dockerfile'
COMPOSE = ROOT / 'compose.yaml'
REQUIREMENTS = ROOT / 'requirements.txt'
REQUIREMENTS_BUILD = ROOT / 'requirements-build.txt'
REQUIREMENTS_IN = ROOT / 'requirements.in'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'

STEP = re.compile(r'^      - (?:name|uses|run|if):', re.M)
USES = re.compile(r'^      - uses: ([^\s@]+)@([0-9a-f]{40})( # v[\d.]+)?\s*$')
ANY_USES = re.compile(r'^      - uses: (\S+)', re.M)
PACKAGE = re.compile(r'^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)==([^\s;\\]+)(;[^\n\\]*)?')
HASH_LINE = re.compile(r'^    --hash=sha256:[0-9a-f]{64}')
ACTION_SHA = re.compile(r'^[0-9a-f]{40}$')

# Measured inventory of the workflow, pinned so a change is a deliberate act.
WORKFLOW_NAME = 'Development checks'
TRIGGERS = ('push', 'pull_request')
JOBS = ('django', 'compose')
STEP_COUNT = 22
RUN_STEP_COUNT = 17
USES_COUNT = 5
DISTINCT_ACTIONS = ('actions/checkout', 'actions/setup-node', 'actions/setup-python')
ERROR_ANNOTATIONS = 10
RUNNER_TEMP_REFERENCES = 35
# Every base image this repository references, by mutable tag, and how often.
MUTABLE_IMAGES = {'postgres:16': 3, 'python:3.11-slim': 1}
# Nothing that would build, publish, describe or sign an artifact appears anywhere in CI.
ABSENT_TOKENS = ('upload-artifact', 'download-artifact', 'build-push-action', 'buildx',
                 'docker push', 'docker tag', 'sbom', 'syft', 'cyclonedx', 'cosign', 'sigstore',
                 'attest', '@sha256:', 'image digest', 'ghcr', 'retention-days', 'id-token',
                 'packages:', 'GITHUB_OUTPUT')


def read(path):
    return path.read_text(encoding='utf-8')


def ci_files():
    """Every file that decides what CI runs or what the development image contains."""
    return [WORKFLOW, DOCKERFILE, COMPOSE, *sorted((ROOT / 'tools').glob('*.py'))]


def triggers(text):
    """The keys of the workflow's `on:` block, in file order."""
    block = text.split('\npermissions:')[0].partition('\non:\n')[2]
    return tuple(re.findall(r'^  ([\w-]+):', block, re.M))


def permissions(text):
    """The top-level `permissions:` mapping, as `(key, value)` pairs."""
    block = re.search(r'^permissions:\n((?:  [^\n]*\n)+)', text, re.M).group(1)
    return tuple(re.findall(r'^  ([\w-]+): (\S+)$', block, re.M))


def packages(text):
    """`[(name, version, marker)]` for every pinned requirement in a lock file."""
    return [(match.group(1), match.group(2), (match.group(3) or '').strip())
            for match in (PACKAGE.match(line) for line in text.splitlines()) if match]


def hash_lines(text):
    return len([line for line in text.splitlines() if HASH_LINE.match(line)])


class WorkflowInventoryTests(SimpleTestCase):
    def test_the_workflow_inventory_is_pinned(self):
        workflows = sorted(WORKFLOW_DIR.glob('*.y*ml'))
        self.assertEqual([path.name for path in workflows], ['checks.yml'],
                         'a workflow was added or renamed')
        text = read(WORKFLOW)
        self.assertEqual(re.search(r'^name: (.*)$', text, re.M).group(1), WORKFLOW_NAME)
        self.assertEqual(triggers(text), TRIGGERS)
        self.assertEqual(tuple(re.findall(r'^  ([a-z][\w-]*):\n    runs-on:', text, re.M)), JOBS)
        self.assertEqual(re.findall(r'^    timeout-minutes: (\d+)$', text, re.M), ['15', '15'])
        self.assertEqual(len(STEP.findall(text)), STEP_COUNT)
        self.assertEqual(len(re.findall(r'^        run: ', text, re.M)), RUN_STEP_COUNT)
        self.assertEqual(len(ANY_USES.findall(text)), USES_COUNT)
        self.assertEqual(permissions(text), (('contents', 'read'),))
        # No job depends on another, and no job runs in a protected environment.
        self.assertEqual(text.count('needs:'), 0)
        self.assertEqual(text.count('environment:'), 0)
        self.assertEqual(len(re.findall(r'^    permissions:', text, re.M)), 0,
                         'a job widened the workflow permissions')

    def test_no_trigger_can_start_a_release(self):
        text = read(WORKFLOW)
        self.assertEqual(set(triggers(text)), set(TRIGGERS))
        for token in ('release:', 'workflow_dispatch', 'schedule:', 'tags:', 'branches:'):
            self.assertNotIn(token, text.split('\npermissions:')[0],
                             'a trigger that could produce a release artifact was added')
        # CI writes annotations and temporary files, and exports nothing a later gate could read.
        self.assertEqual(text.count('::error::'), ERROR_ANNOTATIONS)
        self.assertEqual(text.count('RUNNER_TEMP'), RUNNER_TEMP_REFERENCES)
        self.assertEqual(text.count('GITHUB_OUTPUT'), 0)
        self.assertEqual(text.count('GITHUB_PATH'), 1, 'the restore-drill client shim moved')

    def test_every_action_is_pinned_to_a_commit_sha_with_its_version_commented(self):
        text = read(WORKFLOW)
        refs = [line for line in text.splitlines() if ANY_USES.match(line)]
        self.assertEqual(len(refs), USES_COUNT)
        pinned = []
        for line in refs:
            match = USES.match(line)
            self.assertIsNotNone(match, f'an action is not pinned to a 40-character commit SHA: {line}')
            pinned.append(match.group(1))
            self.assertTrue(ACTION_SHA.match(match.group(2)))
            self.assertTrue(match.group(3), f'an action pin lost its version comment: {line}')
        self.assertEqual(tuple(sorted(set(pinned))), DISTINCT_ACTIONS)
        self.assertEqual(len(set(pinned)), 3, 'the workflow started using a fourth action')
        # Checkout runs twice, and neither run keeps a credential.
        self.assertEqual(pinned.count('actions/checkout'), 2)
        self.assertEqual(text.count('persist-credentials: false'), 2)


class MissingArtifactGateTests(SimpleTestCase):
    def test_nothing_in_ci_builds_publishes_describes_or_signs_an_artifact(self):
        for path in ci_files():
            text = read(path).lower()
            for token in ABSENT_TOKENS:
                with self.subTest(file=path.name, token=token):
                    self.assertNotIn(token.lower(), text,
                                     'CI gained something this record measures as absent')

    def test_the_only_image_the_repository_can_build_is_untagged_and_destroyed(self):
        compose = read(COMPOSE)
        dockerfile = read(DOCKERFILE)
        workflow = read(WORKFLOW)
        # The web service builds from the local context and names no image, so there is nothing
        # to tag, push or digest.
        self.assertEqual(re.findall(r'^    build: (\S+)$', compose, re.M), ['.'])
        self.assertEqual(re.findall(r'^  image: (\S+)$', compose, re.M), [],
                         'the built image gained a name')
        self.assertEqual(re.findall(r'^\s+image: (\S+)$', compose, re.M), ['postgres:16'])
        self.assertEqual(re.findall(r'^FROM (\S+)$', dockerfile, re.M), ['python:3.11-slim'])
        self.assertEqual(dockerfile.count('USER'), 0, 'the development image gained a user')
        self.assertIn('runserver', dockerfile)
        self.assertEqual(dockerfile.splitlines()[0],
                         '# Development image; not a hardened production deployment.')
        # The compose job builds the image to test it and destroys it in the same run.
        self.assertEqual(workflow.count('docker compose up --build -d --wait'), 1)
        self.assertEqual(workflow.count('docker compose down -v'), 1)
        self.assertIn("if: always()", workflow)

    def test_every_base_image_is_referenced_by_mutable_tag(self):
        text = ''.join(read(path) for path in (WORKFLOW, DOCKERFILE, COMPOSE))
        self.assertEqual(text.count('@sha256:'), 0, 'a base image became digest-pinned')
        for image, count in MUTABLE_IMAGES.items():
            self.assertEqual(text.count(image), count,
                             f'the number of references to {image} changed')
        self.assertEqual(sum(MUTABLE_IMAGES.values()), 4)


class DependencyImmutabilityTests(SimpleTestCase):
    def test_both_lock_files_are_fully_hash_pinned(self):
        runtime = packages(read(REQUIREMENTS))
        self.assertEqual(len(runtime), 7)
        self.assertEqual([name for name, _version, _marker in runtime][:4],
                         ['Django', 'asgiref', 'sqlparse', 'psycopg[binary]'])
        self.assertEqual(hash_lines(read(REQUIREMENTS)), 78)
        self.assertEqual(len([marker for _n, _v, marker in runtime if marker]), 3,
                         'the number of environment-marked pins changed')
        build = packages(read(REQUIREMENTS_BUILD))
        self.assertEqual(build, [('pip', '26.3', ''), ('setuptools', '84.2.1', '')])
        self.assertEqual(hash_lines(read(REQUIREMENTS_BUILD)), 4)
        direct = [line for line in read(REQUIREMENTS_IN).splitlines()
                  if line.strip() and not line.startswith('#')]
        self.assertEqual(direct, ['Django==5.2.19', 'asgiref==3.13.0', 'sqlparse==0.6.1',
                                  'psycopg[binary]==3.3.9'])

    def test_every_install_requires_hashes_and_the_pin_is_negatively_controlled(self):
        workflow = read(WORKFLOW)
        dockerfile = read(DOCKERFILE)
        self.assertEqual(workflow.count('--require-hashes'), 2,
                         'the install step and the negative control should both require hashes')
        self.assertEqual(dockerfile.count('--require-hashes'), 2)
        self.assertIn('python -m pip install --require-hashes -r requirements.txt', workflow)
        # The runtime lock is verified before anything is installed.
        self.assertLess(workflow.index('python -m tools.verify_runtime_lock'),
                        workflow.index('pip install --require-hashes'))
        self.assertIn('- name: Reject an incorrect artifact hash', workflow)
        self.assertIn('THESE PACKAGES DO NOT MATCH THE HASHES', workflow)
        # Vulnerability scanning covers the lock and, separately, the built image.
        self.assertEqual(workflow.count('pip-audit==2.10.1'), 2)
        self.assertEqual(workflow.count('npm audit'), 1)
        self.assertEqual(workflow.count('--strict'), 2)


class DocumentedGateTests(SimpleTestCase):
    def test_the_documented_gate_names_what_ci_does_not_do(self):
        gates = read(DEPLOYMENT).partition('## Release gates')[2].partition('\n## ')[0]
        self.assertIn('Pin and scan dependencies and base images, generate SBOM where practical',
                      gates)
        self.assertIn('run tests/migrations on staging and validate rollback compatibility', gates)
        row = [line for line in read(EVIDENCE).splitlines()
               if line.startswith('| CI and supply chain |')]
        self.assertEqual(len(row), 1)
        self.assertIn('immutable production artifacts and image digests', row[0])
        self.assertIn('staging/release gates', row[0])
        # The dependency half of that sentence is implemented; the artifact half is not.
        workflow = read(WORKFLOW)
        self.assertIn('--require-hashes', workflow)
        for token in ('sbom', '@sha256:', 'environment:', 'upload-artifact'):
            self.assertNotIn(token, workflow.lower())
