# 0226 — CI verifies every dependency and produces no artifact

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_ci_artifact_gate.py` (9 tests, ~0.004 s, no database)

## Context

`docs/DEPLOYMENT.md` lists the release gates under *"Pin and scan dependencies and base images,
generate SBOM where practical, run tests/migrations on staging and validate rollback
compatibility"*, and `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"immutable production artifacts
and image digests"* together with *"staging/release gates"* as open on the CI and supply-chain
row. Half of that sentence is implemented and measured: both requirement files are hash-pinned,
CI installs with `--require-hashes`, runs a negative control that proves pip rejects a wrong
artifact hash, verifies the runtime lock before installing anything, and audits the resolved
dependencies and the built image separately.

The other half — an artifact — was neither implemented nor pinned. No suite read
`.github/workflows/checks.yml` at all: `docs/TESTING_STRATEGY.md` describes the action pinning in
prose, and prose does not fail when the file changes. So an unpinned action, a widened
permission, a release trigger or a published image could appear in a diff that no test reads, and
the continued *absence* of an artifact gate was equally invisible: nothing recorded that CI
outputs annotations and temporary files and nothing else.

## Decision

`daroobank/test_ci_artifact_gate.py` reads the four files that decide what CI runs and what the
development image contains (`.github/workflows/checks.yml`, `Dockerfile`, `compose.yaml` and
`tools/*.py`) plus the three requirement files, and pins both halves of the gate: the dependency
immutability that exists, and the artifact machinery that does not.

Parsing is textual, with counts and regular expressions rather than a YAML parse. The runtime lock
is exact and deliberately carries no YAML library, and every measurement here is a shape a regular
expression decides without ambiguity — a `- uses:` line either ends in 40 hexadecimal characters
with a version comment or it does not. The cost is that indentation is part of the contract: the
step patterns match six spaces, so re-indenting the workflow moves the pins.

The absence half is pinned as a token list over the whole of CI, not as a per-step search: if any
of `upload-artifact`, `build-push-action`, `buildx`, `docker push`, `sbom`, `syft`, `cyclonedx`,
`cosign`, `sigstore`, `attest`, `@sha256:`, `ghcr`, `retention-days`, `id-token`, `packages:` or
`GITHUB_OUTPUT` appears in a file that defines CI, a test fails and the record has to be updated
deliberately. That is the point of pinning an absence: the day the gate is built, this suite is
the thing that says so.

## Measured behavior

| Measurement | Result |
|---|---|
| Workflow inventory | one file, `checks.yml`, named `Development checks`; triggers exactly `push` and `pull_request`; 2 jobs (`django`, `compose`), each `timeout-minutes: 15`; 22 steps, 17 of them `run:` steps and 5 `uses:` steps |
| Permissions | one top-level block, exactly `contents: read`; no job-level `permissions:`; no `packages:` and no `id-token:`, so nothing can push an image or mint a build attestation |
| Gating between jobs | `needs:` 0, `environment:` 0 — no job waits on another and no job runs in a protected environment, so there is no staging gate and no approval step |
| Action pinning | all 5 `uses:` references are `owner/name@<40 hex>` with a ` # v…` comment, over 3 distinct actions (checkout, setup-python, setup-node); `persist-credentials: false` on both checkouts |
| What CI outputs | 10 `::error::` annotations, 35 references to `$RUNNER_TEMP`, 1 append to `$GITHUB_PATH` (the restore-drill client shim) and **0** to `$GITHUB_OUTPUT` — no step exports a value a later gate could consume |
| Artifact machinery | zero occurrences of every token in the absence list, across the workflow, `Dockerfile`, `compose.yaml` and all five `tools/` modules |
| The only buildable image | `compose.yaml` builds `.` and names no image, so there is nothing to tag or push; `Dockerfile` starts `FROM python:3.11-slim`, has no `USER` (the image runs as root), serves through `runserver`, and says so in its first line: *"Development image; not a hardened production deployment."* The compose job builds it to test it and ends with `docker compose down -v` under `if: always()` |
| Base images | 4 references, all by mutable tag and none by digest: `postgres:16` three times (workflow service image, the `pg_dump`/`pg_restore` container shim, compose) and `python:3.11-slim` once — so two runs of the same commit can build different images |
| Dependency immutability | `requirements.txt` pins 7 packages with 78 `--hash=sha256:` lines, 3 of them environment-marked; `requirements-build.txt` pins `pip==26.3` and `setuptools==84.2.1` with 4 hashes; `requirements.in` holds the 4 direct pins; `--require-hashes` appears twice in the workflow (install and negative control) and twice in the Dockerfile |
| The negative control | the step `Reject an incorrect artifact hash` writes a lock line with a zeroed hash, requires `pip download --require-hashes` to fail, and requires the failure to say `THESE PACKAGES DO NOT MATCH THE HASHES` |
| Order of operations | `python -m tools.verify_runtime_lock` runs before the install step; `pip-audit==2.10.1 --strict` runs twice (against the lock, and against `pip list` from inside the built image) and `npm audit` once |

## Red checks

Seven, each applied alone and reverted from a backup:

1. Unpinning one checkout to `actions/checkout@v7.0.1` fails 1 test.
2. Adding an `actions/upload-artifact` step with `retention-days` fails 5.
3. Widening the top-level permissions with `packages: write` and `id-token: write` fails 3.
4. Adding a `release:` trigger fails 2.
5. Digest-pinning the postgres service image fails 3 — including the token check, because
   `@sha256:` is on the absence list: pinning a base image is a change this record has to make
   deliberately, not one that slips in.
6. Installing without `--require-hashes` fails 1.
7. Giving the Dockerfile a non-root `USER` fails 1.

## Consequences

- **There is no artifact to deploy.** CI verifies the source and its dependencies and then throws
  everything away; a release would have to build something new, which is exactly the gate
  `docs/DEPLOYMENT.md` names and `docs/PHASE1_RELEASE_EVIDENCE.md` records as open.
- **Base images are the mutable part of an otherwise exact lock.** Python dependencies cannot
  drift — the hashes and the negative control see to that — while `postgres:16` and
  `python:3.11-slim` can, so "the same commit" does not yet mean "the same image".
- Adding a real gate will break these pins on purpose: an artifact step, a registry push, an SBOM
  generator, a signing step, a digest-pinned base image, a staging `environment:` or a
  `packages: write` permission each fails a test here. The suite is written so that the change and
  the record move together.
- What CI does today is still worth its cost: two jobs, 22 steps, a hash-verified install, a
  negative control, two dependency audits, a browser audit and four test phases, all on
  `contents: read` with no persisted checkout credential.

## Limitations

- **Textual parsing.** Indentation, key spelling and step order are part of the contract; a
  semantically identical workflow written differently moves the pins. A YAML parse would need a
  dependency the exact runtime lock does not carry.
- Only this repository's CI is measured. A registry policy, an external pipeline, a manual
  procedure or a hosting-provider control could implement part of this gate elsewhere, and nothing
  here would see it.
- Absence of a token is not absence of a capability: a step could build and publish an artifact
  through a shell command this list does not name. The list covers the ordinary mechanisms.
- Nothing is verified against a registry or a runner. The suite has no network access, so it
  cannot confirm that a pinned action SHA still resolves to the version in its comment, that a
  tag has not moved, or that the hashes in the lock match what PyPI serves today —
  `daroobank/test_lock_metadata.py` covers that comparison offline, and CI's own negative control
  covers the hash rejection.
- The image measurements describe a development image. Whether a hardened production image could
  be built from this repository — non-root, digest-pinned, without `runserver` — is not tested,
  because no such Dockerfile exists.
- **The gate is still open.** This record measures the gap and makes it fail loudly; it does not
  close it. An immutable artifact, its digest, an SBOM, a staging environment and an approval
  step all remain unbuilt and unowned.
