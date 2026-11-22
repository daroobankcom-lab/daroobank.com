# Development guide

## Current local implementation

Requires Python 3.11+ and PostgreSQL. Copy `.env.example` to `.env` and replace the placeholders with unique local values. Never commit credentials: `.env` and `.env.*` files are ignored by Git except `.env.example`, and ignore rules do not remove already tracked files. Compose loads `.env` automatically:

```sh
docker compose up --build
```

The Docker build context excludes environment files other than `.env.example` templates, `.git`, `.venv`, `.cache`, `backups`, `node_modules` and dump/backup files. Existing Compose environment injection is unchanged. Never put secrets or real data in example templates or other build-context paths; ignore rules are not a substitute for secret scanning or access control, and they do not remove files from existing images or Git history. CI checks these exclusions using synthetic files in an ephemeral checkout.

The development stack starts PostgreSQL 16 with a health check and persistent named volume. Django waits for a connection, applies migrations and starts the development server. PostgreSQL is bound only to localhost on `POSTGRES_PORT`; Django inside Compose uses `db:5432`. Do not run multiple migration-starting web replicas or use this development stack as a production deployment. `docker compose down` preserves data; **`docker compose down -v` deletes the database volume**. Changing credentials in `.env` does not update an already-initialized PostgreSQL volume; manage roles/password rotation explicitly.

For Django outside Docker, provision a PostgreSQL database/role or start only the Compose `db` service. Export `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_HOST` (normally `127.0.0.1` for the mapped Compose port); `POSTGRES_PORT` defaults to 5432. Django does not load `.env` itself. To load a trusted shell-compatible `.env`, use `set -a; . ./.env; set +a`; never source untrusted files. `POSTGRES_PASSWORD` can be empty when an explicitly configured peer/certificate authentication method is used. `POSTGRES_SSLMODE` is passed to libpq when set; production must use an appropriate certificate-verified TLS configuration. `POSTGRES_CONN_MAX_AGE` defaults to zero and Django health-checks persistent connections when configured.

```sh
python3 -m venv .venv
.venv/bin/python -m tools.verify_runtime_lock
.venv/bin/pip install --require-hashes -r requirements.txt
export DAROOBANK_DEBUG=1
.venv/bin/python -m tools.wait_for_database
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
.venv/bin/python manage.py test --noinput
.venv/bin/python manage.py makemigrations --check --dry-run
```

### Maintaining Python dependency locks

`requirements.in` records the direct exact runtime pins; `requirements.txt` additionally pins transitive dependencies and SHA-256 hashes of published PyPI release artifacts. Do not install `requirements.in` alongside the lock: pip requires hashes on every requirement in hash-checking mode. The image separately uses `requirements-build.txt` for its pip/setuptools upgrade. CI checks direct pins against the runtime lock, but that small checker is not a dependency resolver and does not verify artifact hashes; pip does that during installation.

To update, review the direct and transitive versions and their dependency metadata, update `requirements.in` and the lock together, obtain and independently review hashes of the intended distribution artifacts from a trusted source, and run the lock check, a clean `pip install --require-hashes -r requirements.txt`, `pip check`, advisory scans and the full tests/CI. Review platform markers and compatible wheels for each target environment. The lock includes source distributions and multiple platforms' artifacts; builds from source have additional build-dependency risks. Docker's base Python/initial pip and the audit tool's dependencies are not covered by these locks. Hashes only verify bytes against the checked-in values; they do not establish publisher identity, provenance or safety. This is not a fully reproducible build.

As an optional maintenance aid, `python -m tools.check_lock_metadata` compares both lock files' hash sets against the current PyPI release JSON for every listed version, including conditional packages, source distributions and yanked files. It needs network access to PyPI, makes no file changes or artifact downloads, and returns nonzero for a mismatch, unsupported lock syntax or registry failure. It reports both extra and missing hashes: a deliberate subset of release artifacts also reports a mismatch, as can later upstream additions or removals. Review the specific artifacts and release changes before updating a lock; do not copy new hashes blindly. The tool relies on PyPI's current metadata and TLS, not an independent trust root; it neither verifies downloaded bytes nor resolves dependencies, evaluates markers, confirms availability/compatibility, checks signatures or proves safety. Pip's hash-checked clean installation and other review remain necessary.

The Django test runner creates and destroys a separate `test_` database; the configured role needs CREATEDB permission and must not share a test name with valuable data or concurrent runs. Do not point the runner at a production server. Tests and local data must be synthetic. `DAROOBANK_SECRET_KEY` is required when debug is off; host names are supplied by `DAROOBANK_ALLOWED_HOSTS`. Development preview accepts `.e2b.app`; production deployment is not configured or authorized.

## Actual layout

- `daroobank/`: Django settings, URL configuration and WSGI entrypoint.
- `catalog/`: narrow presentation model, public search and detail, and development-only private product candidate intake/review.
- `pricing/`: local CSV candidate staging, inspection and preliminary independent review; no public prices or network crawler.
- `sources/`: development-only source-rights assertion and preliminary review ledger, not an authorization gate.
- `ingestion/`: offline time-window inspection and development-only web intake receipts; no scheduler, source worker or network adapter.
- `clinical/`: private synthetic statement drafts, reference assertions and preliminary triage; no clinical approval or public content.
- `templates/`, `static/`: server-rendered Persian pages, shared tokens and locally hosted OFL-licensed Vazirmatn font.
- `docs/`: product, decisions, source research and operational plans.

The current schema and publication flag are not a complete provenance, review, audit or price workflow. There is no public editing interface. Database writes must not be used to bypass clinical and source-rights gates. Never add real credentials, private data or unlicensed source payloads to Git. More domains, independent workers and administrative approvals remain planned; see [architecture](SYSTEM_ARCHITECTURE.md).

## Local price-candidate staging

This local operator-only tool reads an explicitly authorized UTF-8 CSV; it does not download data, publish prices, approve products or alter catalog records. The included price CSV is **synthetic** and must never be treated as Iranian market data. After migrations, try a dry run:

```sh
DAROOBANK_DEBUG=1 .venv/bin/python manage.py stage_price_csv \
  examples/price_candidates.synthetic.csv \
  --source-name 'Synthetic example only' --source-url https://example.org
```

To store an authorized file for later review, supply `--commit --attest-authorized` only when the operator has confirmed that collection and internal storage are permitted. This flag is an operator assertion, not proof of a licence and not an audit trail. Never put actual source files, patient information, credentials or private URLs into Git. `--source-url` must be HTTPS and cannot contain credentials, query parameters or a fragment. Local database and CLI commands are not protected by the web login; restrict access at the operating-system level. The web interface also supports staging with a separate permission and records the authenticated operator. CLI-created or older candidates lack an authenticated stager and cannot be reviewed through the web interface; replays do not change existing provenance.

CSV must contain exactly these column names, once each (order is flexible):

```text
source_record_id,irc,manufacturer,strength,dosage_form,package_description,amount,currency,category,unit,effective_date,source_published_date
```

The last two dates may be blank; otherwise use Gregorian `YYYY-MM-DD`. Currency must be explicitly `RIAL` or `TOMAN`; accepted categories are `official_consumer`, `retail`, `manufacturer`, `wholesale`, `unit`. Accepted units: `package`, `tablet`, `capsule`, `ampoule`, `vial`, `ml`; `unit` category cannot use `package`. Amounts must be positive plain decimals, and conversion must result in a whole Rial without rounding. The source's original value is retained. The input is bounded to 2 MiB and 5,000 rows, and an invalid row aborts the whole file before writing.

To inspect locally staged candidates without changing their status:

```sh
DAROOBANK_DEBUG=1 .venv/bin/python manage.py list_price_candidates --limit 30
# Optional: --status suggested, ambiguous, or unmatched
```

The JSON output includes the original match status and a fresh current suggestion. The initial match is only a snapshot and can become stale; even a current exact match is **not verification**, does not establish IRC scope and must be independently reviewed. This command does not approve candidates. Existing candidate revisions are not changed on replay, and identical source/record/payload combinations are deduplicated. This command records no review decision. There is no tamper-proof audit log, official-source integration, automatic scheduler or public price publication.

## Development-only staff queue

After migrations, create an account **only in an isolated local development environment with synthetic data**:

```sh
DAROOBANK_DEBUG=1 .venv/bin/python manage.py createsuperuser
```

Django prompts interactively for the password; do not place passwords in shell commands, Git or chat. A superuser is broadly privileged and is for local testing only. No accounts or passwords are created automatically. For a less-privileged local viewer, give an existing active account `is_staff=True` and the Django permission `pricing.view_pricecandidate`, either directly or through a group; it does not need edit permissions. Grant/revoke permissions through controlled Django management tooling. Account provisioning and permission changes currently lack an audit workflow.

Start the server in debug mode and visit `/staff/login/`, then `/staff/prices/`. The queue and detail pages are bounded/paginated and accessible only to active staff with that view permission. The pages show the source assertion, original currency, converted Rial amount, and both initial and recalculated current match suggestions; neither suggestion is a review or approval. The match filter and summary counts use the **initial** match status; an independent review filter uses the latest recorded triage decision. Summary counts remain global regardless of filters. Logout is POST-only with CSRF protection. The app never shows candidate prices in public pages or API.

The staff portal is deliberately disabled when `DAROOBANK_DEBUG` is not `1`. This is not a production-ready staff system: MFA, login throttling, hardened credentials, tamper-resistant audit, final approvals, retention policy, production deployment and security validation remain missing. Debug mode can expose diagnostic data and the developer preview can be publicly reachable: never use it with real credentials, sensitive data or real patient information. No source licence has been granted by this implementation.

## Development-only staging and preliminary review

An active staff user needs both `pricing.view_pricecandidate` and `pricing.add_pricecandidate` to use `/staff/prices/import/`. Choose preview (no writes) or stage; staging requires an explicit attestation of permission for collection and internal storage. This is a self-assertion, not a licence check. Only validated structured fields are stored; the original file is not retained by the application. Django may temporarily buffer uploads during a request, and the 2 MiB validation limit is not a reverse-proxy request-size or malware-scanning control.

A different active staff user with both `pricing.view_pricecandidate` and `pricing.review_pricecandidate` can record a reasoned preliminary suggestion acceptance, rejection or deferral on the candidate page. A submitter cannot review their own candidate, including if they have all permissions. Acceptance requires a unique current exact suggestion and a matching product fingerprint; stale review versions and inconsistent stored payload/derived values are rejected. Rejection and deferral do not assert a product match. Events store the reviewer, reason, timestamp, candidate snapshot and product identity snapshot/hash. The detail page shows at most 25 recent events. A review is neither price approval nor proof of source rights, and it cannot publish.

Identical replays do not alter the original submitter or attestation, including legacy or CLI-created records; these must be investigated through a future controlled provenance workflow, not edited directly to bypass separation. The model's ordinary `save()`/`delete()` guard is **not** database immutability: bulk ORM operations and direct SQL can alter or delete history. The hash is a consistency fingerprint, not a signature or proof of untampered source provenance; the source URL is not part of the payload hash. PostgreSQL row locks protect rows actually locked, but product matching cannot prevent concurrent insertions or edits from creating ambiguity. Optimistic checks are useful for sequential stale forms, not a proven concurrent authorization or matching guarantee. Do not rely on this local workflow for real data or release decisions; production needs a designed isolation/locking strategy, transaction and concurrency tests against its actual DB, durable audit protections and independent security review.

## Development presentation pages and API

Search links to `/products/<id>/`; `/api/v1/products/<id>/` returns the same presentation fields as search. Both reuse public visibility checks, show only published dated records with required identity fields and valid HTTPS source URLs without embedded credentials, and return a generic 404 for missing, unpublished or ineligible records. They are deliberately noindex, no-store and excluded from the sitemap pending real governance. A timestamp or `published` flag is not clinical approval or proof of source rights. No prices, availability or clinical guidance are provided. URLs are displayed to users: do not enter private URLs, query tokens or personal information. A source is not automatically fetched or validated as authoritative.

Search uses forward cursor pagination: each request validates at most 150 SQL-matched candidates, fetches one additional candidate for continuation detection and returns at most 30 valid results. A page with no visible records may still have a next page. Ordering and membership can change between requests; it is not a snapshot or a completeness guarantee. The row limit does not bound database filtering or sorting work. Bypassed model writes can corrupt metadata or leave search projections stale. Do not use the development implementation or its local empty/synthetic database as a medical or market source.

## Development API contract

The implemented public read endpoints are specified in [OpenAPI 3.0.3](openapi.json), available locally at `/api/v1/openapi.json`. It describes current behavior only, not planned clinical, price, write or authentication APIs. Search cursors are query-bound and expire after one hour; changing or deleting the anchor can invalidate a cursor, so restart the search. Cursors are signed, not encrypted, and expose an anchor ID. They do not authorize access. Search terms and cursor URLs can be logged by web servers; never search with patient data. The schema and tests do not establish source rights, security, accessibility or production readiness.

## Development-only product candidate intake

With `DAROOBANK_DEBUG=1`, `/staff/products/` is an internal queue of source assertions, separate from `ProductPresentation`. Active staff need `catalog.view_productcandidate` to see the queue and details, plus `catalog.add_productcandidate` to preview or stage at `/staff/products/import/`. Staff with only catalog view permission are redirected to that queue after ordinary login; explicit safe `next` still takes precedence. Use separate development-only accounts: there is no seeded account or audited provisioning.

Upload the **synthetic** [`examples/product_candidates.synthetic.csv`](../examples/product_candidates.synthetic.csv) for a preview. UTF-8 CSV must contain exactly the columns `source_record_id,name_fa,name_en,manufacturer,strength,dosage_form,package_description,irc` in any order. `name_en` and `irc` may be empty. Input is limited to 1 MiB and 1,000 records; all rows must validate before any write. No original file is retained by application logic, but Django may buffer an upload temporarily. Source URL must be HTTPS without userinfo, query or fragment. Only structured fields are stored. Operators must exclude sensitive/patient data, credentials, private URLs and data lacking permission; the application does not detect all such material. Staging requires an explicit assertion of rights for collection and internal storage, not proof of those rights. Preview does not write. Duplicate `(source URL, record ID, payload fingerprint)` replays preserve the first authenticated submitter; changed source content creates a separate revision. No network retrieval, automatic matching decision or merging is performed.

A different active staff user with `catalog.view_productcandidate` and `catalog.review_productcandidate` can record a reasoned preliminary decision: refer for further review, reject, or defer. A submitter cannot review their own record. The queue can filter by the latest review decision or absence of a review; these are triage labels, not approvals. Reviews capture the actor, time, structured candidate snapshot and fingerprint; the detail page shows the 25 latest. Stale review versions, changed payload/source and invalid candidate structures fail closed in sequential use. No action here creates, updates or publishes a `ProductPresentation`, nor authorizes a price or clinical content.

PostgreSQL locks selected rows, but the full review and editing workflow under concurrency has not been proven safe. Model `save()`/`delete()` guards do not block bulk ORM or direct SQL changes; hashes are not signatures or proof of rights, identity or an immutable audit trail. The fingerprint covers source name, URL and structured fields, but not actor or attestation; the snapshot records them and privileged DB edits can alter both. Do not use this local flow for real data or release decisions. Production requires reviewed rights governance, authorization, concurrent transaction design/tests on its actual database, durable audit, retention, request limits and independent security review.

## Product comparison clues

On `/staff/products/<id>/`, staff who can view product candidates can inspect up to 10 other revisions with exactly the same stored source URL and source-record ID. Original field differences are displayed; a separate marker identifies text that becomes equal after search normalization, not verified equivalence. Up to 10 other indexed candidate records and 10 eligible public presentations sharing the normalized IRC are also inspected. Draft/unpublished catalog presentations are deliberately excluded regardless of the user's other roles. Empty IRC means this comparison is not performed; a missing result, a single result, or matching normalized strings never establishes uniqueness or identity. Ineligible or inconsistent rows among the inspected records are skipped with a warning. When more than 10 indexed rows exist, the view warns that the comparison was truncated. There is no automatic identity decision, merge, publication or source-rights verification.

Candidate normalized IRC is backfilled by migration `0004` and set during staging. The migration walks existing candidates and updates them individually; plan backups, maintenance time and a rollback/restore procedure before applying it to any non-development database. A malformed, overlong or inconsistent index is excluded or stops the current candidate's comparison; sequential review also rejects a mismatch. Other stale/missing indexes can hide rows without detection, including `ProductPresentation` indexes, because ordinary direct writes, bulk operations and SQL can bypass the controlled intake. The cap bounds application inspection, not all database sorting/scan work; no production-scale benchmark exists. Comparisons are recomputed on viewing, are not saved in review snapshots and are not rechecked when a review is submitted. Concurrent changes, database collation, stale indexes and differing identifier semantics can change results. A reviewer must not use this feature as an approval or complete reconciliation, and no claim of source access or validation follows from a displayed record.

## Development price revision comparison and matching limits

The staff price detail page compares at most 10 other revisions of the same exact source URL and source-record ID, ordered by descending internal ID, **not** effective or publication date. It shows the other source amount and original currency, exact Rial conversion, category, unit, effective/source-publication dates (including unknown), and collection time. A signed integer difference is computed as **this candidate minus the other**, only after both candidates pass structured/integrity checks and share the exact source name, category and unit and the same nonempty normalized IRC, manufacturer, strength, form and package text. Rial/Toman differences use only the explicit 1 Toman = 10 Rial conversion; no rounding, FX assumption or percentage is introduced. This conditional arithmetic does not verify product identity, source authority, pricing eligibility, chronology, price validity or a market trend. Source URL is outside the existing price payload hash. Other revisions may be missing or changed, and comparisons are not saved in or rechecked at review time. The row bound does not bound database sort/scan cost.

Matching for price staging and fresh suggestions now requires all identity fields to remain nonempty after normalization and rejects control/surrogate characters in them. Older rows that fail current validation remain stored but cannot pass integrity checks for review/comparison; investigate them rather than modifying data to bypass controls. Up to 101 presentations with the same indexed IRC are fetched: if more than 100 exist, the result is conservatively `ambiguous` even if only one or none among the first 100 would match. An ambiguous status may therefore mean the bound was exceeded, not necessarily that multiple exact matches exist. A stale or absent IRC index can still hide records, and database scans, concurrent insertion and source identity are not proven safe. The CLI current suggestion reports `invalid` for malformed identity fields. No product or price is approved or published.


## Development-only source-rights assertions

After migration, active staff with `sources.view_sourceclaim` can visit `/staff/sources/`. The separate `sources.add_sourceclaim` permission is also required to record an assertion; `sources.review_sourceclaim` plus view is required for preliminary review by a different user from the original recorder. Assign these permissions directly or via controlled Django groups, just as with the price queue. `add_sourceclaimreview` by itself does not grant review access. Superusers have all permissions but cannot review their own assertions. These are local-development roles only; do not use real secrets, private URLs, patient data or actual agreements in this portal.

A claim records an asserted owner, source and evidence HTTPS URLs, optional non-sensitive note, at least one claimed scope (collection, internal storage or republication), optional Gregorian start/end dates, actor and timestamp. URLs must not contain credentials, query parameters or fragments. Neither URL is fetched or verified; the evidence URL is shown as text, not opened automatically. A date label only compares the claimed dates with the current date in Asia/Tehran; missing dates remain unknown and an in-range label is not legal validity. Fields are checked and fingerprinted; identical source URL + payload replays preserve the original recorder, while changed values create a new assertion. This fingerprint covers assertion fields, **not the recorder or timestamp**, and is not a signature.

A separate reviewer records further-review referral, rejection or deferral with reason and a snapshot; there is no approval decision. The queue is paginated by 20 and may be filtered by the latest review. Detail shows at most 25 recent reviews. Product and price candidate details show at most five newest claims for an **exact source URL** only to users with the separate source view permission; an invalid URL or no result is not evidence of no permission. These hints are not captured in candidate review snapshots and do not gate staging or review. Recording, reviewing or finding a claim never authorizes source use, collection, storage or publication and causes no network request or public write.

The workflow is not a tamper-proof audit: model `save()`/`delete()` guards do not stop bulk ORM or direct SQL. PostgreSQL locks only rows actually selected. Sequential stale-form and fingerprint checks are not a concurrency guarantee. Production needs independently verified evidence and legal decisions, revocation enforcement, access control, durable audit, retention and tested database concurrency before any real source use. The existing CSV attestation is independent of this ledger and remains an operator assertion, not proof of rights.


## Offline ingestion-window inspection

No source access or scheduler is enabled. This command emits JSON for a supplied timezone-aware ISO-8601 instant (or the system clock if omitted):

```sh
DAROOBANK_DEBUG=1 .venv/bin/python manage.py inspect_ingestion_window --at 2026-11-22T20:00:00Z
DAROOBANK_DEBUG=1 .venv/bin/python manage.py inspect_ingestion_window --start 09:00 --end 10:00 --timezone UTC --at 2026-11-22T09:30:00+00:00
```

Defaults are `23:00`–`01:00` in `Asia/Tehran`, from local date D to D+1. The start is inclusive and end exclusive; equal times are invalid. The output identifies current or next window, its UTC/local boundaries, the checked instant, and `dispatch_enabled: false`. Nonexistent or ambiguous local boundary times fail with a command error, rather than guessing. Inputs require ASCII `HH:MM` and a valid installed IANA timezone; `--at` must contain an offset. The OS or Python environment must provide current IANA timezone data; results also depend on a correct system clock. Results for future dates can change as timezone rules change.

The debug-only `/staff/operations/window/` page provides the same read-only calculation for active staff with at least one of `catalog.view_productcandidate`, `pricing.view_pricecandidate` or `sources.view_sourceclaim`. Parameters are per request and never stored. It links from each authorized queue; GET/HEAD only, staff privacy headers and the normal debug gate apply. Neither page nor command changes the source ledger or candidates, contacts sources, starts jobs, checks rights, saves schedule configuration or enforces a real window. Production requires the safeguards listed in [ADR 0002](ARCHITECTURE_DECISIONS/0002-offline-ingestion-window.md).

Private product, price and source intake now consistently reject URLs with even empty `?`/`#` delimiters, empty credentials, controls or invalid Unicode, in addition to the existing HTTPS/no-secret rules. Review reasons reject invalid Unicode and non-text control characters. Previously staged records with newly invalid URLs are not rewritten and fail preliminary review until investigated through a future controlled repair workflow; do not use direct DB edits to bypass review. These checks do not prove a URL or source is legitimate, licensed or safe to fetch.


## Development-only CSV intake receipts

After `migrate`, a successful **web** product or price staging request creates a receipt in the same database transaction as the candidate writes. Visit `/staff/operations/imports/` from either queue. Active staff with `catalog.view_productcandidate` see product receipts, and those with `pricing.view_pricecandidate` see price receipts; users with both see both. Source-only staff cannot see receipts. Filtering and pagination operate after permission filtering; cross-domain detail URLs are 404. Add permissions are still required for actual staging. Staff privacy headers and the debug-only gate apply.

Each receipt has asserted source name and URL, actor and server timestamp, row count, created count and duplicate count. Price receipts also capture current match suggestion/ambiguity/unmatched counts for **all input rows including duplicates**, not just new records. These are request-time calculations, not product identity verification and not necessarily the original or current candidate status. Replaying a file creates another receipt, even if no new candidates are created. No raw file, filename or file-level hash is retained. For new receipts, a separate row-outcome manifest stores logical data-row ordinal, asserted source record ID, candidate payload hash and candidate reference, whether it was new or a duplicate, and the request-time suggestion status for prices. Thus it records candidate membership but cannot reconstruct or prove the original file. Ordinals are data-row positions, not necessarily physical CSV line numbers. The candidate records retain their own structured source data under their existing rules. Upload handling may temporarily buffer the file.

Web staging creates receipts only for successful requests after this feature was introduced: previews, validation failures, rolled-back writes, previous imports, CLI staging and direct calls to the original importer services are absent. Local code can also invoke the receipt wrappers directly with an authorized user; those service calls are not protected by the web debug gate. Absence is not evidence of no import. A receipt is an internal summary, not proof of source rights, verified data, completeness, publication, immutable audit or actor identity. No file or candidate content is published by this feature. Model guards do not prevent bulk ORM or direct SQL modifications, and production concurrency and crash recovery are not proven. There is no request idempotency key, failure log, retention policy or signed audit; production requires additional design and testing as described in [ADR 0003](ARCHITECTURE_DECISIONS/0003-web-intake-receipts.md).


### Row outcomes and candidate links

Receipt manifests were added after the original receipt feature. New receipt-backed staging records up to 1000 product or 5000 price row outcomes in the same transaction as the candidates and receipt. Earlier receipts explicitly show “manifest unavailable”; historical membership is not reconstructed. The web interface shows 25 rows per page after checking structural totals, ordinal sequence and domain/status consistency. Each link is shown only when the current candidate's source, ID and payload pass consistency checks against the recorded outcome. A mismatch hides the affected row's details; structural mismatch hides the list. These checks cannot prove file origin, completeness or integrity against someone with database write access.

Each candidate detail lists up to five recent distinct receipt references as *unverified clues*, ordered by internal ID. Duplicate rows within one receipt yield one receipt link; older receipts and CLI/direct imports are absent. A zero-result list does not prove the candidate had no prior import; count limits do not bound database scan/sort costs. A replay has a new receipt and each input row is marked duplicate even when it refers to an older candidate, whose original actor is not changed. Price row suggestions are computed for that request and may differ from the candidate's original or current suggestion.

The manifest stores source record IDs and candidate payload hashes, not the file or its hash. Hashes are not signatures; price candidate hash does not include the source URL. FKs protect linked candidates/receipts from ordinary Django deletion, but bulk modifications and SQL can still alter data; deletion, retention and repair policy are unresolved. This is not an audit trail, source authorization, evidence of file contents or a publication mechanism. Use only synthetic, non-sensitive data and see [ADR 0004](ARCHITECTURE_DECISIONS/0004-intake-row-manifest.md).


## Development-only clinical draft triage

After migrations, `/staff/clinical/` is available only in the debug portal to active staff with `clinical.view_clinicaldraft`; adding a draft or revision additionally requires `clinical.add_clinicaldraft`, and reviewing another author's version requires `clinical.review_clinicaldraft`; the reviewer must also differ from every recorder of the current supplementary references. Assign these separately or through controlled Django groups. A user with only the clinical view permission is directed to this queue after login. Superusers can access all domains but cannot review a version they authored. Direct service calls are not protected by the web debug gate; restrict OS/database access. The checkbox on the web form is a self-attestation, not verification.

Create only synthetic, non-sensitive content: free-text subject, audience, title, statement, asserted reference title, exact location and HTTPS URL; asserted author, source version and Gregorian publication/access dates may be blank. Dates are not verified and no chronology is inferred; source URLs cannot include credentials, query parameters or fragments and are never fetched. The text field is intended for one statement but cannot enforce that scope. The draft has no product/ingredient identity and the citation, source rights, safety, evidence quality and reviewer qualifications are not checked. Users with `sources.view_sourceclaim` may see up to five exact-URL source-claim hints for the primary citation; neither their presence nor absence authorizes use. No clinical content is public or published.

To amend, create a new version from an existing one with a reason; subject and audience must match exactly. Branching and identical drafts are allowed, and review does not carry over. The version records an immediate parent ID and its fingerprint. Only the new version and direct parent's payload are checked; earlier ancestry and concurrent branching are not certified. Another permitted staff member, who authored neither the draft nor any current supplementary reference, can refer for further review, reject or defer with a reason. There is no clinical approval or publish action. Queue filters use audience and latest preliminary decision, paginated 20; detail shows at most 10 direct child versions and 25 review events. Limits do not bound DB scan/sort cost.

The hash covers draft fields and parent link, not author/time, and is not a signature or proof of source or consent. Ordinary model guards do not stop bulk ORM/SQL mutation. Optimistic checks detect sequential stale submissions; PostgreSQL locks the selected draft row; this does not prove every concurrency or authorization scenario. There is no qualified-review verification, verified multi-reference evidence, original-file storage, controlled retention/correction/withdrawal, durable audit or production security. Never use this portal for real clinical or patient content; see [ADR 0005](ARCHITECTURE_DECISIONS/0005-clinical-draft-triage.md).


### Supplementary reference assertions and review snapshots

From a draft detail, staff with clinical view and add permissions can submit up to ten supplementary assertions **for that version** in addition to its primary reference. Each has asserted title, HTTPS URL, exact location, optional author/version and Gregorian publication/access dates, plus a user-selected relationship: claimed support, claimed contradiction, context or unclear. The relation and dates are not checked and do not establish actual support, contradiction, independence, access, rights or clinical quality. The same payload on the same version is deduplicated and retains its original recorder; changing the relation makes a distinct assertion. References are not automatically carried to child versions. Form acknowledgement is not evidence and only synthetic data should be used.

Add and review forms carry a fingerprint of the current supplementary set; changed data, invalid stored assertions or an over-limit set stop the action rather than silently omitting references. A different staff member from both the draft author and *all current supplementary assertion recorders* may record preliminary triage. New reviews snapshot the reference fields, IDs, recorder IDs and fingerprints, and detail pages show the bounded historical snapshot and its identifier comparison with the current set. A matching identifier does not verify evidence or the reviewer, and a changed identifier does not erase the old review. Reviews predating the feature have no supplementary snapshot; no history is fabricated. The queue filter still reflects the latest recorded review regardless of later reference changes; check details. Older direct `review_draft` service calls without a set fingerprint remain accepted only when the supplementary set is empty; web forms always require it.

The set hash covers ordered assertion IDs, payload hashes and recorder IDs, not timestamps; neither hash nor snapshot is a signature. The service-level ten-item cap, row locking and sequential stale checks do not by themselves prove all concurrency cases. Bulk ORM/SQL can bypass validation or alter history; `PROTECT` foreign keys and ordinary model guards are not a tamper-proof audit or retention policy. No source is fetched, no clinical review/rights are established and no content is published. See [ADR 0006](ARCHITECTURE_DECISIONS/0006-clinical-evidence-assertions.md).


## PostgreSQL backup and isolated restore

PostgreSQL's `pg_dump` and `pg_restore` are external client utilities, not an application backup service. Use a client version at least as new as the server; access must be restricted and authorized. Dumps contain all user data, password hashes, sessions and other private information, are unencrypted by default and are not committed. Choose a trusted private location, encrypt and retain according to policy, and test restoration separately. A volume alone is not a backup.

For a **synthetic development** database, after exporting the PostgreSQL variables above and installing matching PostgreSQL client tools:

```sh
export PGHOST="$POSTGRES_HOST" PGPORT="${POSTGRES_PORT:-5432}" PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD"
umask 077
# shell noclobber fails if the destination already exists.
(set -C; pg_dump --format=custom --no-owner --no-acl --dbname="$POSTGRES_DB" > /private/backup/dev.dump)
pg_restore --list /private/backup/dev.dump > /dev/null
# Only use a new, isolated drill database. Fail if it already exists.
createdb daroobank_restore_drill
pg_restore --exit-on-error --single-transaction --no-owner --no-acl --dbname=daroobank_restore_drill /private/backup/dev.dump
POSTGRES_DB=daroobank_restore_drill .venv/bin/python manage.py migrate --check
POSTGRES_DB=daroobank_restore_drill .venv/bin/python manage.py check
```

The example directories must already exist and be private. PostgreSQL/OS environment variables can be visible to privileged local processes; use an appropriate secret manager or restricted `.pgpass` for production. Set `PGSSLMODE` and certificate variables as required. `createdb` needs privileges and must target an isolated test server; remove drill databases only under an explicit local retention policy. `pg_restore --list` checks the archive structure, not the restored data; check expected records, relationships and application behavior on the isolated copy. Database-only dumps do not include roles, external assets or all cluster configuration. `migrate --check` only checks pending migrations. Restore commands never target the active database. No automatic encryption, off-host retention, cadence or monitoring is provided; see [ADR 0007](ARCHITECTURE_DECISIONS/0007-backup-policy.md).



## Concurrent PostgreSQL CSV staging

Committed product and price CSV stages take a transaction-level PostgreSQL advisory lock keyed by the staging domain and **exact validated source URL**. This also applies to the direct import services and CLI commit paths; preview never acquires the lock. The lock is held until the outermost transaction commits or rolls back, including any receipt and manifest writes. Same-domain, same-URL stages wait rather than interleave their overlapping unique-key inserts in opposite order. File row order and manifest ordinals remain unchanged; replay still creates a separate web receipt while preserving the first candidate recorder.

This protocol coordinates only participating current-version writers. Older workers, direct SQL and bulk writes bypass it; different URL spellings do not share a key. Different domains and URLs normally do not wait on each other, though hash collisions can serialize unrelated stages. Waiting can be prolonged by an outer transaction or slow code; there is no application-level timeout, fairness or automatic retry. A configured PostgreSQL lock timeout can cause an error and transaction rollback. Do not call another staging operation or external service from row callbacks; taking several source locks in inconsistent orders can deadlock. Deploy the same protocol across writers. This is not a network authorization, matching lock, audit or exactly-once guarantee. See [ADR 0010](ARCHITECTURE_DECISIONS/0010-staging-concurrency.md).

## Development-only catalog quality inspection

The private, read-only `/staff/catalog/quality/` page requires an active staff user with `catalog.view_productpresentation`; that permission is separate from candidate, price, source and clinical permissions. The DEBUG-only portal, privacy headers and normal login apply. A user with only this presentation permission is routed here on login. The page shows IDs, technical status and fixed warnings, not the underlying names or URLs. Granting the permission nevertheless allows staff to enumerate internal IDs and technical flags, including drafts. Use only synthetic, non-sensitive data.

For a trusted local operator, the management command uses the same inspector and prints JSON; it does not apply web authentication or the DEBUG gate:

```sh
DAROOBANK_DEBUG=1 .venv/bin/python manage.py inspect_catalog_quality
DAROOBANK_DEBUG=1 .venv/bin/python manage.py inspect_catalog_quality --after 50
```

Each call inspects up to 50 ascending IDs greater than `after`, plus one lookahead; use the returned `next_after` value for the next call, not a presumed count. It compares stored search/IRC projections with the current fields; warns about control/invalid text and URLs that fail the stricter private-source URL policy; checks the current public technical eligibility prefilter and predicate; and flags normalized IRC duplicates only among valid-index rows in **that batch**, including unpublished rows. URLs with queries may pass the existing public filter but fail this separate advisory policy. A corrupt text field reports public-filter status as unknown rather than asserting passage or rejection. No names or URLs are returned, and nothing is fetched or changed.

No warnings does not mean the content, source, permission, identity or clinical data is correct. The public flag and filter are not approval. No checks establish uniqueness across the full catalog; changed/deleted/new rows can make successive pages inconsistent, and empty results are not proof of complete catalog quality. Limit is by rows, not bytes, query cost or duration. The command and page cannot fix issues and are not a production monitoring, release or audit system. See [ADR 0008](ARCHITECTURE_DECISIONS/0008-catalog-quality-inspection.md).


### Indexed IRC clues across catalog batches

From the quality page, choose **بررسی سرنخ‌های IRC** for a presentation ID. The separate read-only page inspects other rows with the same stored normalized IRC across the whole catalog, including unpublished rows. Its anchor must have a nonempty IRC and a consistent normalized projection. Each returned row is checked again against its original IRC; an inconsistent stored index is flagged, not presented as a consistent clue. No names, actual IRCs or source URLs are deliberately displayed. The page requires the same `catalog.view_productpresentation` permission and DEBUG-only staff gate as the quality scan.

Trusted local operators may use the same lookup independently of web permissions:

```sh
.venv/bin/python manage.py inspect_catalog_irc --id 1
# If next_cursor is not null, copy the exact token from the JSON result:
.venv/bin/python manage.py inspect_catalog_irc --id 1 --cursor 'PASTE_RETURNED_CURSOR'
```

Use an existing presentation ID; the commands and data are synthetic examples. Each page examines at most 50 indexed candidates and one lookahead, ordered by ID. Cursor tokens expire after one hour, are signed and bind the anchor ID and its normalized code; an invalid, expired or changed anchor requires restarting. Tokens contain IDs and a keyed code digest, not raw IRC text. They are not encrypted or an authorization mechanism: a known debug secret and guessable codes can compromise the digest, and URLs/tokens may appear in logs.

This targeted lookup can find consistent indexed clues beyond the original 50-row scan, but it is **not a complete catalog-wide duplicate audit**. Missing or stale indexes can conceal records; edits between requests can change results, and a finished scan does not prove uniqueness. It does not establish product identity, interchangeability, source rights or clinical validity. Database work and response time are not bounded by the row cap. See [ADR 0011](ARCHITECTURE_DECISIONS/0011-indexed-irc-inspection.md).


## Synthetic identity chain

In the development-only staff portal, assign `catalog.view_identityworkspace` to inspect; add `catalog.add_identityworkspace` to create and `catalog.review_identityworkspace` for independent package triage. Create ingredients, then a formulation using ingredient IDs and explicit component quantities/units, then a product using the formulation ID, then a package using the product ID. Only synthetic nonconfidential data is permitted. Inspect the package and have a different staff member, not an author of any chain element, submit preliminary triage. A stale review or changed graph conflicts; reload before reassessing. Package details page review history in descending ID order (25 per page) and distinguish a matching review from a different coherent historical snapshot, which can be expanded; the form is available only on the newest page, and conflicts require a reload and reassessment. Pages are not a database snapshot; inconsistent history is hidden. These checks do not authenticate the snapshot or review. These records do not affect public products and source URLs are not fetched. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md) for limitations and bypasses.


## Synthetic package corrections

From an internally consistent private package detail, staff with identity view/add permissions can create a synthetic correction. Inspect the current graph and latest preliminary review, provide changed package/source values and a reason; the product remains the same. A new package and immediate-parent link are recorded atomically; the earlier package and its reviews stay unchanged. Independent branches are allowed and no branch is automatically current. On stale graph or review, reload and reassess. Links are browsable in bounded pages and inconsistent links are hidden. Review applies to the new graph, not to the parent or correction link. Do not infer identity, equivalence, authorization or clinical approval. See [ADR 0013](ARCHITECTURE_DECISIONS/0013-synthetic-package-revisions.md).


## Synthetic ingredient, formulation and product corrections

From a private ingredient, formulation or product detail, staff with identity view/add permissions may create an asserted correction and supply a reason. A new child and immediate-parent link are created; dependent records are not updated and no branch is automatically selected. Formulation corrections retain the same ingredients and order; product corrections retain the same formulation. Create independent records for changes outside those bounds. Branches and links are not proof of equivalence or clinical approval, and package reviews do not validate them. Use synthetic data only; see [ADR 0014](ARCHITECTURE_DECISIONS/0014-synthetic-component-revisions.md).


## Inspect a synthetic correction path

From an identity record detail, authorized staff can open the read-only parent-path inspector. It examines up to 20 immediate links per section and stops if a graph or link is inconsistent; use the next link for an older section. No recorded parent does not prove origin or completeness. A stale/expired cursor requires starting again. Data may change between pages and earlier links are not rechecked; this is not a review or proof of correctness. See [ADR 0015](ARCHITECTURE_DECISIONS/0015-synthetic-lineage-inspection.md).


### Optional isolated browser smoke test

For synthetic-only Chromium checks, use Linux x86-64, Node 22.17+ and follow the dedicated database setup and command in [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test). Never run against production or real data.
