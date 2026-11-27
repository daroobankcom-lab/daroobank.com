# The CI and supply-chain plan, and what one run of this pipeline actually leaves behind

`docs/CI_SUPPLY_CHAIN_PLAN.md` prices that gate; `docs/PHASE1_RELEASE_EVIDENCE.md` carries the
CI and supply-chain subject as an open gate whose whole requirement list is quoted verbatim in
[Requirements](#requirements) below. What the row
asks for — independent review, immutable artifacts, digests, OS and transitive review,
staging/release gates and rollback — is measured here against what a run of
`.github/workflows/checks.yml` produces today, what its locks prove, and what a later gate would
find readable. [ADR 0237](ARCHITECTURE_DECISIONS/0237-ci-supply-chain-plan.md) records what this
document says and what it measures.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat a green run of a development workflow as a release. Its prices
are counted from the pins and files below, not prototyped: no workflow line, no dependency, no
environment key, no action and no tool was added or changed to write it. **Nothing is
implemented.** No new header, no new workflow, no new environment variable, no new dependency, no
new control and no new command exists in this tree because of this file. The measurements were
taken from the checked-in files, from the GitHub Actions API for a completed run, and from local
re-runs of the audits this workflow performs; the temporary probe that collected them has been
deleted.

## What is true today, measured

Counted on this tree by parsing the files CI decides from, by reading the steps and timestamps of
a completed run, and by re-running the audits locally. They are pinned by
`daroobank/test_ci_supply_chain_plan.py`, next to the inventory `daroobank/test_ci_artifact_gate.py`
already holds.

### The workflow's shape

* **`.github/workflows/checks.yml` is 217 lines: 2 jobs, 22 steps, 17 `run:` steps and 5 `uses:`
  references.** The jobs are `django` and `compose`; every step is one of `- name:`, `- uses:`,
  `- run:` or `- if:`, matched at its six-space indent.
* **Every action reference is pinned.** The five `uses:` lines resolve to three distinct actions
  — `actions/checkout` twice, `actions/setup-python` twice, `actions/setup-node` once — each a
  40-character commit SHA with a version comment (`# v7.0.1`, `# v7.1.0`, `# v7.1.0`), and both
  checkout steps set `persist-credentials: false` (2 occurrences).
* **Permissions and triggers are minimal.** Exactly one top-level permission: `contents: read`;
  no job-level `permissions:` block (0). The triggers are push and pull_request only, with no
  `release:`, `workflow_dispatch`, `schedule:`, `tags:` or `branches:` key above the permissions
  line. There is one `if:` condition in the file — `if: always()` on the final cleanup step — and
  both jobs carry `timeout-minutes: 15`.
* **There is no gate to join to.** 0 `environment:` keys on any job and 0 `needs:` edges: the two
  jobs start in parallel and neither waits for the other or runs in a protected environment.
* **Exports are job-local.** 0 `GITHUB_OUTPUT`, 0 `GITHUB_ENV` and 1 `GITHUB_PATH` (the
  `pg16-tools` shim directory, appended inside the `django` job only). The workflow emits 10
  `::error::` annotations and refers to `RUNNER_TEMP` 35 times.

### What one run produces

* **Window and outcome.** On run `46004021177` (merge commit `4a0d148`, both CI checks green) the
  run started `2026-11-27T13:04:57Z` and finished `2026-11-27T13:17:24Z` — 12m27s end to end,
  conclusion `success`, both jobs running in parallel.
* **The `django` job ran 740 s** (`13:05:01Z` → `13:17:21Z`): dependency install 3 s, the
  negative-control download below under 1 s, configuration checks 3 s, the synthetic test suite
  9m22s, the isolated restore drill 16 s, the encrypted restore probe 10 s, the `pip-audit` step
  13 s, `npm ci` 1 s, `npm audit` under 1 s, and the Chromium tests 1m49s. Everything this job
  writes goes to `$RUNNER_TEMP` (logs, audit virtual environments, the client shim) except one
  `>> "$GITHUB_PATH"` line, which later steps of the same job read and no later job sees.
* **The `compose` job ran 69 s** (`13:05:01Z` → `13:06:10Z`): stack build and health 35 s, image
  package audit 11 s, volume-survival check 9 s, final teardown 10 s. Its probe step writes 14
  files into the workspace itself — `.env`, `.env.local`, `context-probe.dump`, and sentinel or
  example files under `.cache/`, `backups/`, `node_modules/` and `tests/browser/` — all inside the
  ephemeral checkout, none uploaded.
* **The only image build is `docker compose up --build`**, which builds `compose.yaml`'s `web`
  service from `build: .` with no `image:` key, so the image exists only under the compose
  project's default name on the runner. The last step runs `docker compose down -v` under
  `if: always()`, removing the containers, the network and the named `postgres_data` volume in
  the same run that created them.
* **Nothing is uploaded.** The workflow contains 0 `upload-artifact` and 0 `download-artifact`
  steps, 0 `docker push` and 0 `ghcr` references, and the repository's artifacts API reports a
  `total_count` of 0. There is no tag, no release and no signature step.

### The locks and their audits

* **`requirements.txt` is 94 lines: 7 exact pins and 78 `--hash=sha256:` lines**; three of the
  pins carry environment markers. `requirements-build.txt` pins `pip==26.3` and
  `setuptools==84.2.1` with 4 hash lines. `tests/browser/package-lock.json` is 298 lines with 22
  `sha512-` integrity entries. `--require-hashes` appears twice in the workflow (the install and
  the negative control) and twice in the Dockerfile.
* **The negative control is exact.** The step writes
  `printf 'Django==5.2.19 --hash=sha256:%064d\n' 0` — a 64-zero digest — into
  `$RUNNER_TEMP/bad-hash.txt`, runs `pip download --require-hashes` against it, requires that
  command to fail, and requires the log to contain `THESE PACKAGES DO NOT MATCH THE HASHES`.
  Re-run locally in the same shape on 2026-11-27 at 14:11Z: exit code 1, the marker found exactly
  once, error text `ERROR: THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE.`
* **`tools/verify_runtime_lock.py` proves consistency, not authenticity.** Its own summary: it
  will "Fail when a direct runtime pin and the checked-in artifact lock diverge", and it "is not
  a full requirements parser or a supply-chain authenticity verifier". The workflow runs it
  before anything is installed.
* **`tools/check_lock_metadata.py` compares the checked-in hashes with current PyPI metadata,
  read-only.** Re-run locally on 2026-11-27 at 14:12:05Z it reported `requirements.txt: checked 7
  releases`, `requirements-build.txt: checked 2 releases` and `Hash sets match current PyPI
  metadata; this does not establish authenticity or safety.` The workflow never calls it (0
  occurrences).
* **Both audits are strict and were green.** The workflow installs `pip-audit==2.10.1` twice (a
  lock virtual environment and an image virtual environment) and passes `--strict` twice, plus
  one `npm audit --audit-level=info`. Re-run locally on 2026-11-27: the lock audit at 14:11:44Z
  printed `No known vulnerabilities found` and exited 0; the npm audit at 14:12:21Z printed
  `found 0 vulnerabilities` and exited 0. On run `46004021177` all four audit and control steps —
  check direct runtime pins, reject an incorrect artifact hash, audit resolved Python
  dependencies, audit browser test dependencies — concluded `success`, as did the compose image
  audit.

### What a later gate could read

* **Nothing exports a value.** 0 `GITHUB_OUTPUT` and 0 `GITHUB_ENV` writes mean no step produces
  an output, environment or artifact that a later step or job could consume; the single
  `GITHUB_PATH` append is visible only to later steps of the `django` job.
* **Nothing orders the jobs.** 0 `needs:` edges and 0 `environment:` keys: a staging or release
  gate has no predecessor to wait on and no protected environment to require approval in. The
  repository's environments API reports a `total_count` of 0, and the artifacts API reports a
  `total_count` of 0.
* **What would have to exist for an enforceable gate**, all absent today: a job that `needs:`
  the current jobs (or a `workflow_run`/release trigger), values written to `GITHUB_OUTPUT` or an
  uploaded artifact for that job to read, an `environment:` with required reviewers on the
  promoting job, and an artifact or image digest — the thing being promoted — recorded somewhere
  the gate can compare against.

### What does not exist, as counts

* In the four files that decide what CI runs and what the image contains (`.github/workflows/
  checks.yml`, `Dockerfile`, `compose.yaml`, `tools/*.py`): `sbom` 0, `syft` 0, `cyclonedx` 0,
  `cosign` 0, `sigstore` 0, `attest` 0, `@sha256:` 0, `retention-days` 0, `id-token` 0, `ghcr` 0,
  `buildx` 0, `docker push` 0, `docker tag` 0, `upload-artifact` 0, `GITHUB_OUTPUT` 0.
* **`.github/` holds exactly 1 file** — `.github/workflows/checks.yml` — and the repository
  contains 0 Dependabot or Renovate configuration files, so nothing proposes an update to the
  five action SHAs or the four base-image tags.
* **Four base-image references, all mutable.** `postgres:16` at `.github/workflows/checks.yml`
  line 13 (the service container), line 80 (the `docker run` wrapper for `pg_dump`/`pg_restore`)
  and `compose.yaml` line 6 (the `db` service); `python:3.11-slim` at `Dockerfile` line 2 — 4
  base-image references and 0 digests, so the same commit can build a different image tomorrow.
* **The one buildable image is development-only.** `compose.yaml` builds `.` with no `image:`
  key (0 configured tags), the Dockerfile contains 0 `USER` directives — the container runs as
  root — and its `CMD` serves through `runserver`; the same run destroys it with
  `docker compose down -v`. The Dockerfile's own first line says it: `# Development image; not a
  hardened production deployment.`

## Requirements

The gate's open cell in `docs/PHASE1_RELEASE_EVIDENCE.md`, quoted verbatim — the suite pins each
sentence in this plan and in that row:

1. *independent review, immutable production artifacts and image digests, OS/transitive
   dependency review, staging/release gates and rollback*
2. *CI produces no artifact at all: nothing is uploaded, tagged, pushed, described by an SBOM or
   signed, no step exports a value a later gate could read, no job waits on another or runs in a
   protected environment*
3. *all four base-image references (`postgres:16` three times, `python:3.11-slim` once) are
   mutable tags rather than digests, so the same commit can build a different image*
4. *The only image the repository can build is a development image — untagged, root-owned,
   serving through `runserver`, destroyed inside the run*
5. *CI success is not a security certification*

The development cell of the same row already pins the half that exists, and this plan prices
against it unchanged:

6. *pins all five action references to 40-character commit SHAs with their versions commented*
7. *installs both hash-pinned lock files with `--require-hashes` behind a negative control that
   requires pip to reject a zeroed hash*
8. *audits the resolved dependencies and the built image with `pip-audit --strict`*

`docs/DEPLOYMENT.md` states the release gate this row implements the first half of:

9. *Pin and scan dependencies and base images, generate SBOM where practical, run
   tests/migrations on staging and validate rollback compatibility*

and [ADR 0226](ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md) records what the existing suite
then proved — that CI *outputs annotations and temporary files and nothing else*.

## Candidate approach and decisions required

The measured starting point is a 217-line workflow of 2 jobs and 22 steps whose five action
references are SHA-pinned, whose locks are hash-pinned and negatively controlled, and which
produces 0 artifacts, 0 exports, 0 environment gates and 0 digests across 4 mutable base-image
references. Everything below is contingent on the decisions it names, and none of them is
answered here.

1. **What artifact, if any, would a release gate promote, and who approves a promotion?** Today
   CI produces no artifact at all, so the first decision is whether a wheel, an image digest or
   nothing at all is the unit a gate would hold.
2. **Which of the four base-image references become digest-pinned, who refreshes the digests,
   and how is the `docker run` wrapper at `checks.yml` line 80 kept in step with the service
   image at line 13?** Pinning two of the three `postgres:16` references and leaving the third
   on a tag would still let a run resolve two different servers.
3. **What SBOM is generated, for which scope (the two Python locks, the npm tree, the built
   image, all three), with which tool, stored where, and who reviews it?** The row says
   "generate SBOM where practical" and today the count of generators is 0.
4. **What is signed, with which key material, who verifies the signature before a deploy, and
   what happens when verification fails?** `cosign`, `sigstore` and `id-token` each occur 0
   times, so both the signing act and the verification act are undecided.
5. **How are OS and transitive dependencies reviewed, and on what cadence?** The locks cover the
   Python and npm trees and both audits are strict, but `python:3.11-slim`'s OS packages are
   never scanned, the audit tool's own dependencies are installed fresh on every run, and
   nothing proposes an update when a new advisory lands.
6. **What is the staging/release gate topology — which environment names, which required
   reviewers, which `needs:` edges, and which value does the gate read?** An enforceable gate
   needs all four of the things counted as absent under
   [What a later gate could read](#what-a-later-gate-could-read).
7. **What does rollback mean here — previous image digest, previous commit, or database
   migrations reversed — who triggers it, and when was it rehearsed?** The row lists rollback
   next to staging/release gates; the deployment guide lists it as a gate to validate before
   release, and no run of this pipeline performs one.
8. **What does "independent review" cover — every workflow change, every release, every digest
   bump — who counts as independent, and where is the review recorded?** Nothing in `.github/`
   records a review, an approval or an environment protection rule today.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the measured pipeline as it is** | nothing | 0 workflow lines, 0 actions, 0 environment keys and 0 dependencies move; the 22/17/5 inventory, the `contents: read` permission, both audits and the negative control stay exactly as measured | all eight decisions, and whether a pipeline that produces no artifact can satisfy a gate that asks for one |
| **B. Write the release-gate contract into documents only** | `docs/DEPLOYMENT.md`, `docs/SECURITY.md` and the evidence row each gain a paragraph naming the artifact, digest, review and rollback a gate would require | documents reworded only; every new link moves `LINK_COUNT` in `daroobank/test_document_links.py` and the row's five requirement quotes must survive verbatim or this plan's suite fails | whether a documented contract that no pipeline enforces survives the next workflow change — the artifact half of the deployment guide has been prose since ADR 0226 |
| **C. Digest-pin the four base-image references** | `checks.yml` lines 13 and 80, `compose.yaml` line 6 and `Dockerfile` line 2 each carry `@sha256:…` | the workflow is read by six suites — `test_ci_artifact_gate.py` (`MUTABLE_IMAGES`, `@sha256:`), `test_backup_recovery_plan.py` (`WORKFLOW_FACTS`, `IMAGE_REFERENCES`), `test_environment_documentation.py`, `test_mfa_implementation_plan.py`, `test_network_tls_plan.py` and this plan's suite — so each pin is recounted from its own assertion message; no lock, permission or trigger line moves | who refreshes the digests when the upstream tags move (decision 2), and whether a digest-pinned dev image changes anything for a release that does not exist |
| **D. Add an SBOM and a signature step** | new steps in `checks.yml` for generation and signing, and a permission to obtain an OIDC token | `STEP_COUNT` and `RUN_STEP_COUNT` move in `test_ci_artifact_gate.py`, `ABSENT_TOKENS` (`sbom`, `syft`, `cyclonedx`, `cosign`, `sigstore`, `attest`, `id-token`) become failures that suite deliberately pins as absent, `permissions` stops being `contents: read` alone, and a new action reference moves `USES_COUNT` and the distinct-action set | which tool, which key, which scope, who verifies and what a failed verification does (decisions 3 and 4) |
| **E. Add a protected staging environment and a `needs:` gate** | a promoting job with `environment:` and `needs:`, plus `GITHUB_OUTPUT` or an artifact for it to read | `environment:` moves from 0 in `test_ci_artifact_gate.py` and `test_backup_recovery_plan.py`, `needs:` moves from 0 in both, `GITHUB_OUTPUT` moves from 0 in both, and the gate inventories this plan and ADR 0237 quote as absent have to be rewritten | which environment, which reviewers, what the gate reads and what it promotes (decisions 1 and 6), and nothing here stages anything to promote |
| **F. Adopt an update bot for actions, locks and base images** | a `.github/dependabot.yml` or Renovate configuration | 1 new file under `.github/` — the workflow-file inventory stays `['checks.yml']` because the bot config is not a workflow — plus a review load of one PR per pinned action, lock and tag; no suite counts `.github/` files today, so nothing fails until a suite is written for it | whether automated PRs are the independent review the gate asks for (decision 8), and who merges them |
| **G. Declare supply-chain hardening out of Phase 1 scope** | the evidence row stops asking for artifacts, digests, review, gates and rollback | the row's five requirement quotes — pinned by this suite — must be rewritten in place, `docs/DEPLOYMENT.md` drops the gate sentence quoted above, and ADR 0226's context sentence stops matching its source | who accepts a pipeline with no artifact, no digest and no gate, which is a decision for an owner and not for this file |

## Required behavior before any release gate

1. **The unit of promotion is defined** — a wheel, an image digest, or an explicit decision that
   neither exists — and it is produced by a step whose output later jobs read through
   `GITHUB_OUTPUT` or an uploaded artifact.
2. **All four base-image references carry digests** — both `checks.yml` occurrences, the compose
   `db` service and the Dockerfile `FROM` — refreshed by a documented process, so a run cannot
   resolve a different image than the one that was reviewed.
3. **An SBOM exists for the reviewed scope** and a human has reviewed it; generation, storage
   and cadence are named, not assumed from the row's "where practical".
4. **A signature exists and the deployer verifies it**, with key material, verification step
   and failure behavior written down before the first signed build.
5. **The promoting job runs in a protected environment** with required reviewers, waits on the
   jobs it depends on through `needs:`, and reads a value those jobs actually exported.
6. **Rollback is defined and rehearsed** — what is rolled back, by whom, in what order relative
   to migrations — with the evidence recorded where a release review can find it.
7. **Independent review is recorded** for every workflow change and every digest or lock bump:
   who reviewed, when, and against which measurements.

## Verification before any enablement

- Re-derive every count in this document from the checked-in files rather than trusting it: the
  217-line workflow's 2 jobs, 22 steps, 17 `run:` steps, 5 SHA-pinned `uses:` references, the
  single `contents: read` permission, the push/pull_request triggers, the one `if: always()`, both
  15-minute timeouts, 0 `environment:` keys, 0 `needs:`, 0 `GITHUB_OUTPUT`, 0 `GITHUB_ENV`, 1
  `GITHUB_PATH`, 10 annotations and 35 `RUNNER_TEMP` references.
- Re-read a completed run's step timestamps and re-run both audits locally: the 12m27s window,
  the 740 s and 69 s job durations, the negative control's exit code 1 with its hash-mismatch
  marker, `No known vulnerabilities found` from the lock audit and `found 0 vulnerabilities` from
  the npm audit, and the four green audit steps on the same run.
- Re-count the locks and the absences: 94 lines, 7 pins, 78 hash lines, 4 build-tool hashes, 298
  lockfile lines with 22 `sha512-` entries, 4 mutable base-image references with 0 digests, 1
  file under `.github/`, and 0 occurrences of every SBOM, signature, digest, push, retention and
  export token in the CI-deciding files.
- Run `daroobank/test_ci_supply_chain_plan.py`, `daroobank/test_ci_artifact_gate.py`,
  `daroobank/test_document_links.py`, `daroobank/test_backup_recovery_plan.py`,
  `daroobank/test_environment_documentation.py`, `daroobank/test_mfa_implementation_plan.py`,
  `daroobank/test_network_tls_plan.py`, `daroobank/test_release_notes_structure.py` and
  `daroobank/test_secret_rotation_plan.py`, and take every global pin this plan moves from their
  failure messages instead of from this document.
- Confirm that no workflow line, dependency, environment key, action, SBOM generator or signing
  tool has appeared while this plan claims none has, and re-run that confirmation after any
  later edit to this file or its record.
- Record named owners and evidence for artifact review, digest refresh, signing verification and
  rollback rehearsal. No release gate, no signed build and no Phase 1 completion follows from
  this plan or its suite.
