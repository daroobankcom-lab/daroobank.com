# 0237 — the CI and supply-chain plan, and what one run leaves behind

Date: 2026-11-27
Status: accepted
Suite: `daroobank/test_ci_supply_chain_plan.py` (10 tests, ~0.01 s, no database)

## Context

[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries the CI and supply-chain
subject as an open gate: *"independent review, immutable production artifacts and image digests,
OS/transitive dependency review, staging/release gates and rollback"*, while *"CI produces no
artifact at all: nothing is uploaded, tagged, pushed, described by an SBOM or signed, no step
exports a value a later gate could read, no job waits on another or runs in a protected
environment"* and *"all four base-image references (`postgres:16` three times,
`python:3.11-slim` once) are mutable tags rather than digests, so the same commit can build a
different image"*. [DEPLOYMENT.md](../DEPLOYMENT.md) states the release gate itself — *"Pin and
scan dependencies and base images, generate SBOM where practical, run tests/migrations on
staging and validate rollback compatibility"* — and [ADR 0226](0226-ci-artifact-gate.md) already
pinned the implemented half: SHA-pinned actions, hash-pinned locks, a negative control, and the
strict audits, proving that CI *"outputs annotations and temporary files and nothing else"*.

What nobody had measured was the run itself: how long a green run takes and what each job
writes, which values a later gate could read (none — 0 `GITHUB_OUTPUT`, 0 `GITHUB_ENV`, 0
`needs:`, 0 `environment:`), what the local re-runs of the audits report, and the absence
inventory as counts rather than as prose. The row's own caveat stands over all of it: *"CI
success is not a security certification."*

## Decision

Record [CI_SUPPLY_CHAIN_PLAN.md](../CI_SUPPLY_CHAIN_PLAN.md) as the measurement and the proposal
for this gate, in the form [ADR 0227](0227-read-audit-plan.md),
[ADR 0230](0230-mfa-implementation-plan.md), [ADR 0232](0232-backup-recovery-plan.md) and
[ADR 0234](0234-network-tls-plan.md) established: an unowned proposal, priced options, numbered
decisions, no implementation. This record changes no workflow line. The plan states **Nothing is
implemented.** — no new workflow, no new dependency, no new environment key, no new action and
no new tool — and this suite holds it to that claim, to its ten quotes (each must exist both in
the plan and in the document it comes from), and to its measured numbers, re-derived live from
the files CI decides from. The eight decisions — the unit of promotion, digest pinning and its
refresh process, the SBOM's scope and reviewer, signing and verification, OS/transitive review
cadence, the gate topology, rollback, and what independent review covers — stay open; answering
them is not this record's business.

## Measured behavior

One completed run (`46004021177`, head `4a0d148`), the checked-in files, and local re-runs of
the audits, all on this tree:

* **The workflow's shape.** `.github/workflows/checks.yml` is 217 lines: 2 jobs (`django`,
  `compose`), 22 steps, 17 `run:` steps and 5 `uses:` references to 3 distinct actions, each
  pinned to a 40-character commit SHA with a version comment; exactly one top-level permission
  (`contents: read`), no job-level permissions, push and pull_request only, one `if: always()`,
  two 15-minute timeouts, 0 `environment:` keys, 0 `needs:`, 0 `GITHUB_OUTPUT`, 0 `GITHUB_ENV`,
  1 job-scoped `GITHUB_PATH`, 10 `::error::` annotations, 35 `RUNNER_TEMP` references and 2
  `persist-credentials: false`.
* **What one run produces, with its window.** `2026-11-27T13:04:57Z` → `2026-11-27T13:17:24Z`
  (12m27s, `success`): the `django` job 740 s (synthetic tests 9m22s, restore drill 16 s,
  encrypted probe 10 s, lock audit 13 s, Chromium tests 1m49s), the `compose` job 69 s (stack 35
  s, image audit 11 s, volume check 9 s, teardown 10 s). The django job writes only
  `$RUNNER_TEMP` plus one `>> "$GITHUB_PATH"` line; the compose job writes 14 probe files into
  the workspace and builds the only image the repository can build, then `docker compose down -v`
  under `if: always()` removes the containers, network and `postgres_data` volume. 0
  `upload-artifact` steps; the artifacts API reports `total_count` 0.
* **The locks and the controls.** `requirements.txt` 94 lines, 7 exact pins, 78 hash lines;
  `requirements-build.txt` 2 pins and 4 hashes; `package-lock.json` 298 lines with 22 `sha512-`
  entries; `--require-hashes` twice in the workflow and twice in the Dockerfile. The negative
  control's zeroed digest was re-run locally on 2026-11-27 at 14:11Z: `pip download` exited 1
  with `THESE PACKAGES DO NOT MATCH THE HASHES`. `tools/verify_runtime_lock.py` runs before any
  install and proves pin/lock consistency only; `tools/check_lock_metadata.py`, re-run at
  14:12:05Z, reported `requirements.txt: checked 7 releases`, `requirements-build.txt: checked 2
  releases` and `Hash sets match current PyPI metadata; this does not establish authenticity or
  safety.`, and the workflow never calls it.
* **Both strict audits, re-run locally.** The lock audit at 2026-11-27T14:11:44Z printed `No
  known vulnerabilities found` (exit 0); the npm audit at 14:12:21Z printed `found 0
  vulnerabilities` (exit 0). On run `46004021177` the four audit and control steps and the
  compose image audit all concluded `success`.
* **The absence inventory, as counts.** In the CI-deciding files: `sbom` 0, `syft` 0,
  `cyclonedx` 0, `cosign` 0, `sigstore` 0, `attest` 0, `@sha256:` 0, `retention-days` 0,
  `id-token` 0, `ghcr` 0, `buildx` 0, `docker push` 0, `docker tag` 0, `upload-artifact` 0,
  `GITHUB_OUTPUT` 0. `.github/` holds exactly 1 file and the repository holds 0 Dependabot or
  Renovate configurations. Four base-image references — `postgres:16` at `checks.yml` lines 13
  and 80 and `compose.yaml` line 6, `python:3.11-slim` at `Dockerfile` line 2 — and 0 digests.
  The Dockerfile has 0 `USER` directives and serves through `runserver`; compose builds `.` with
  no `image:` key. The environments API reports `total_count` 0.

## Red checks

After the plan, the suite and the neighbour patches existed, twenty-four mutations were applied
one at a time to a byte-identical backup of the tree (`sha256sum` recorded before, re-verified
after every restore, final check rc=0), each followed by a run of
`daroobank/test_ci_supply_chain_plan.py`, each run required to fail. Every mutation went red and
the suite ended green:

1. Plan: `## Requirements` renamed — `test_the_plan_states_its_own_shape`.
2. Plan: `### What one run produces` renamed — `test_the_plan_states_its_own_shape`.
3. Plan: decision 8 unnumbered — `test_the_plan_states_its_own_shape`.
4. Plan: "The selected approach is to adopt Dependabot now." inserted —
   `test_the_plan_is_an_unowned_proposal_that_implements_nothing` (forbidden-selection list).
5. Plan: requirement quote 1 (`independent review, immutable production artifacts ...`) replaced
   — `test_the_plan_quotes_the_requirements_it_is_priced_against`.
6. Evidence row: the same gate sentence truncated —
   `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
7. ADR 0226: its quoted annotation sentence reworded —
   `test_the_plan_quotes_the_requirements_it_is_priced_against`.
8. Plan: `217 lines` became `218 lines` — `test_the_plan_states_the_measured_numbers`.
9. Plan: every `12m27s` became `13m00s` — `test_the_plan_states_the_measured_numbers`.
10. Plan: `The \`django\` job ran 740 s` became `750 s` —
    `test_the_plan_states_the_measured_numbers`.
11. Plan: `requirements.txt\` is `94 lines` became 95 —
    `test_the_plan_states_the_measured_numbers`.
12. Plan: `4 base-image references and 0 digests` became `1 digest` —
    `test_the_plan_states_the_measured_numbers`.
13. Workflow: `timeout-minutes: 15` became `16` —
    `test_the_workflow_shape_is_recounted_from_the_file`.
14. Workflow: an `environment: staging` key added to the django job —
    `test_nothing_the_plan_prices_has_been_implemented`.
15. Workflow: an `echo … >> "$GITHUB_OUTPUT"` line added —
    `test_nothing_the_plan_prices_has_been_implemented`.
16. Workflow: `permissions` widened from `contents: read` to `contents: write` —
    `test_the_workflow_shape_is_recounted_from_the_file`.
17. `requirements.txt`: last line removed (94 → 93) —
    `test_the_locks_and_the_negative_control_are_recounted`.
18. Dockerfile: `USER nobody` added — `test_the_absences_are_counts_not_memory`.
19. compose.yaml: `image: myapp:latest` added to the `web` service —
    `test_the_absences_are_counts_not_memory`.
20. CHANGELOG: this entry's heading date changed —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
21. ADR index: the 0237 bullet deleted —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
22. DEPLOYMENT: the plan link removed —
    `test_the_neighbour_documents_and_the_evidence_row_link_the_plan`.
23. `tools/sbom_scan.py` created — `test_nothing_the_plan_prices_has_been_implemented`.
24. `package-lock.json`: one `sha512-` prefix changed (22 → 21) —
    `test_the_locks_and_the_negative_control_are_recounted`.

Three mutations initially slipped — a wrapped quote matched against unwrapped text, a count whose
first occurrence was replaced while a second survived, and two assertions too weak to notice a
changed changelog heading or a four-space compose `image:` key — which is why the suite's
changelog and compose assertions exist in their present form; each was re-run red after the fix.

## Consequences

* The gate row in [PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) now carries the
  run's measurements in its evidence cell while every quoted gate sentence stays verbatim in
  place — five in the open cell, three in the development cell — because this suite and
  `daroobank/test_ci_artifact_gate.py` pin them; the open half points at the plan's eight
  decisions and states that answering them remains unassigned work.
* [DEPLOYMENT.md](../DEPLOYMENT.md), [TESTING_STRATEGY.md](../TESTING_STRATEGY.md),
  [SECURITY.md](../SECURITY.md), [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md) and
  [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) each gained a sentence that names what was
  measured and links the plan and this record; [CHANGELOG.md](../CHANGELOG.md) carries the
  entry.
* The pipeline now has a second, claim-shaped reader beside `daroobank/test_ci_artifact_gate.py`:
  that suite pins the inventory, this one pins the plan that prices changing it — so an option
  that moves `STEP_COUNT`, `ABSENT_TOKENS`, `environment:` or `GITHUB_OUTPUT` fails both the
  suite that owns the pin and the plan that quotes it.
* Global pins move with this record and must be recounted from the tree rather than from this
  text: `DOCUMENT_COUNT`, `ADR_COUNT`, `LINK_COUNT`, `SUITE_LINE_COUNT` in
  `daroobank/test_document_links.py`, `TEST_MODULE_COUNT` in the suites that quote it,
  `DOCS_MARKDOWN_COUNT` in `daroobank/test_backup_recovery_plan.py`, and `LOGIN_ROUTE_TESTS`
  only if this suite's file names the login route (it does not).
* Nothing here edits the workflow, the locks, the permissions or the tools. Any of those remains
  a change for whoever answers the decisions, with its price already counted in the plan's option
  table.

## Limitations

- **The run window is one run.** The 12m27s duration, the 740 s and 69 s jobs and the step
  timings come from run `46004021177` on one day; queue times, cache hits and GitHub's runner
  fleet will move them, and the plan says so by dating every number.
- **The audits were re-run locally, not scraped from CI.** The job-log endpoints live on hosts
  this environment cannot reach, so `No known vulnerabilities found` and `found 0
  vulnerabilities` are this machine's re-runs of the exact commands at the recorded times, with
  the corresponding CI steps cited only by their `success` conclusion.
- **No artifact exists to inspect.** There is no SBOM, signature or digest in this repository, so
  nothing here evaluates a tool, a key or a registry — only their absence and the eight decisions
  that would pick them.
- **Textual parsing, like ADR 0226's suite.** Counts and regular expressions decide every
  measurement; re-indenting the workflow or renaming a step moves pins in the six suites that
  read it, each of which must be recounted from its own assertion message.
- **A green run is not a certification.** The suite pins documents, counts and files; it cannot
  tell whether a gate should exist, whether an external pipeline elsewhere holds the artifacts this
  one does not, or who may approve a release — the row's own sentence is the last word: *CI
  success is not a security certification.*
