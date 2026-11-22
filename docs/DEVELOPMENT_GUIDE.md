# Development guide

## Current local implementation

Requires Python 3.11+ and dependencies pinned in `requirements.txt`. No credentials or patient data are needed. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DAROOBANK_DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
.venv/bin/python manage.py test
.venv/bin/python manage.py makemigrations --check --dry-run
```

`.env.example` is a placeholder reference; this application does not automatically load `.env`. SQLite and the development secret are for local use only. `DAROOBANK_SECRET_KEY` is required when debug is off; host names are supplied by `DAROOBANK_ALLOWED_HOSTS`. Development preview accepts `.e2b.app`; production deployment is not configured or authorized.

## Actual layout

- `daroobank/`: Django settings, URL configuration and WSGI entrypoint.
- `catalog/`: narrow presentation model, public search and detail, and development-only private product candidate intake/review.
- `pricing/`: local CSV candidate staging, inspection and preliminary independent review; no public prices or network crawler.
- `templates/`, `static/`: server-rendered Persian pages, shared tokens and locally hosted OFL-licensed Vazirmatn font.
- `docs/`: product, decisions, source research and operational plans.

The SQLite schema and publication flag are not a complete provenance, review, audit or price workflow. There is no public editing interface. Database writes must not be used to bypass clinical and source-rights gates. Never add real credentials, private data or unlicensed source payloads to Git. More domains, PostgreSQL, independent workers and administrative approvals remain planned; see [architecture](SYSTEM_ARCHITECTURE.md).

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

Start the server in debug mode and visit `/staff/login/`, then `/staff/prices/`. The queue and detail pages are bounded/paginated and accessible only to active staff with that view permission. The pages show the source assertion, original currency, converted Rial amount, and both initial and recalculated current match suggestions; neither suggestion is a review or approval. Filters and counts use the **initial** match status. Logout is POST-only with CSRF protection. The app never shows candidate prices in public pages or API.

The staff portal is deliberately disabled when `DAROOBANK_DEBUG` is not `1`. This is not a production-ready staff system: MFA, login throttling, hardened credentials, tamper-resistant audit, final approvals, retention policy, production deployment and security validation remain missing. Debug mode can expose diagnostic data and the developer preview can be publicly reachable: never use it with real credentials, sensitive data or real patient information. No source licence has been granted by this implementation.

## Development-only staging and preliminary review

An active staff user needs both `pricing.view_pricecandidate` and `pricing.add_pricecandidate` to use `/staff/prices/import/`. Choose preview (no writes) or stage; staging requires an explicit attestation of permission for collection and internal storage. This is a self-assertion, not a licence check. Only validated structured fields are stored; the original file is not retained by the application. Django may temporarily buffer uploads during a request, and the 2 MiB validation limit is not a reverse-proxy request-size or malware-scanning control.

A different active staff user with both `pricing.view_pricecandidate` and `pricing.review_pricecandidate` can record a reasoned preliminary suggestion acceptance, rejection or deferral on the candidate page. A submitter cannot review their own candidate, including if they have all permissions. Acceptance requires a unique current exact suggestion and a matching product fingerprint; stale review versions and inconsistent stored payload/derived values are rejected. Rejection and deferral do not assert a product match. Events store the reviewer, reason, timestamp, candidate snapshot and product identity snapshot/hash. The detail page shows at most 25 recent events. A review is neither price approval nor proof of source rights, and it cannot publish.

Identical replays do not alter the original submitter or attestation, including legacy or CLI-created records; these must be investigated through a future controlled provenance workflow, not edited directly to bypass separation. The model's ordinary `save()`/`delete()` guard is **not** database immutability: bulk ORM operations and direct SQL can alter or delete history. The hash is a consistency fingerprint, not a signature or proof of untampered source provenance; the source URL is not part of the payload hash. `select_for_update` has no row-locking effect on SQLite, and product matching cannot prevent concurrent insertions or edits from creating ambiguity. Optimistic checks are useful for sequential stale forms, not a proven concurrent authorization or matching guarantee. Do not rely on this local workflow for real data or release decisions; production needs a designed isolation/locking strategy, transaction and concurrency tests against its actual DB, durable audit protections and independent security review.

## Development presentation pages and API

Search links to `/products/<id>/`; `/api/v1/products/<id>/` returns the same presentation fields as search. Both reuse public visibility checks, show only published dated records with required identity fields and valid HTTPS source URLs without embedded credentials, and return a generic 404 for missing, unpublished or ineligible records. They are deliberately noindex, no-store and excluded from the sitemap pending real governance. A timestamp or `published` flag is not clinical approval or proof of source rights. No prices, availability or clinical guidance are provided. URLs are displayed to users: do not enter private URLs, query tokens or personal information. A source is not automatically fetched or validated as authoritative.

Search uses forward cursor pagination: each request validates at most 150 SQL-matched candidates, fetches one additional candidate for continuation detection and returns at most 30 valid results. A page with no visible records may still have a next page. Ordering and membership can change between requests; it is not a snapshot or a completeness guarantee. The row limit does not bound database filtering or sorting work. Bypassed model writes can corrupt metadata or leave search projections stale. Do not use the development implementation or its local empty/synthetic database as a medical or market source.

## Development API contract

The implemented public read endpoints are specified in [OpenAPI 3.0.3](openapi.json), available locally at `/api/v1/openapi.json`. It describes current behavior only, not planned clinical, price, write or authentication APIs. Search cursors are query-bound and expire after one hour; changing or deleting the anchor can invalidate a cursor, so restart the search. Cursors are signed, not encrypted, and expose an anchor ID. They do not authorize access. Search terms and cursor URLs can be logged by web servers; never search with patient data. The schema and tests do not establish source rights, security, accessibility or production readiness.

## Development-only product candidate intake

With `DAROOBANK_DEBUG=1`, `/staff/products/` is an internal queue of source assertions, separate from `ProductPresentation`. Active staff need `catalog.view_productcandidate` to see the queue and details, plus `catalog.add_productcandidate` to preview or stage at `/staff/products/import/`. Staff with only catalog view permission are redirected to that queue after ordinary login; explicit safe `next` still takes precedence. Use separate development-only accounts: there is no seeded account or audited provisioning.

Upload the **synthetic** [`examples/product_candidates.synthetic.csv`](../examples/product_candidates.synthetic.csv) for a preview. UTF-8 CSV must contain exactly the columns `source_record_id,name_fa,name_en,manufacturer,strength,dosage_form,package_description,irc` in any order. `name_en` and `irc` may be empty. Input is limited to 1 MiB and 1,000 records; all rows must validate before any write. No original file is retained by application logic, but Django may buffer an upload temporarily. Source URL must be HTTPS without userinfo, query or fragment. Only structured fields are stored. Operators must exclude sensitive/patient data, credentials, private URLs and data lacking permission; the application does not detect all such material. Staging requires an explicit assertion of rights for collection and internal storage, not proof of those rights. Preview does not write. Duplicate `(source URL, record ID, payload fingerprint)` replays preserve the first authenticated submitter; changed source content creates a separate revision. No network retrieval, automatic matching decision or merging is performed.

A different active staff user with `catalog.view_productcandidate` and `catalog.review_productcandidate` can record a reasoned preliminary decision: refer for further review, reject, or defer. A submitter cannot review their own record. The queue can filter by the latest review decision or absence of a review; these are triage labels, not approvals. Reviews capture the actor, time, structured candidate snapshot and fingerprint; the detail page shows the 25 latest. Stale review versions, changed payload/source and invalid candidate structures fail closed in sequential use. No action here creates, updates or publishes a `ProductPresentation`, nor authorizes a price or clinical content.

SQLite `select_for_update` does not provide row locks: concurrent reviews/edits have not been proven safe. Model `save()`/`delete()` guards do not block bulk ORM or direct SQL changes; hashes are not signatures or proof of rights, identity or an immutable audit trail. The fingerprint covers source name, URL and structured fields, but not actor or attestation; the snapshot records them and privileged DB edits can alter both. Do not use this local flow for real data or release decisions. Production requires reviewed rights governance, authorization, concurrent transaction design/tests on its actual database, durable audit, retention, request limits and independent security review.

## Product comparison clues

On `/staff/products/<id>/`, staff who can view product candidates can inspect up to 10 other revisions with exactly the same stored source URL and source-record ID. Original field differences are displayed; a separate marker identifies text that becomes equal after search normalization, not verified equivalence. Up to 10 other indexed candidate records and 10 eligible public presentations sharing the normalized IRC are also inspected. Draft/unpublished catalog presentations are deliberately excluded regardless of the user's other roles. Empty IRC means this comparison is not performed; a missing result, a single result, or matching normalized strings never establishes uniqueness or identity. Ineligible or inconsistent rows among the inspected records are skipped with a warning. When more than 10 indexed rows exist, the view warns that the comparison was truncated. There is no automatic identity decision, merge, publication or source-rights verification.

Candidate normalized IRC is backfilled by migration `0004` and set during staging. The migration walks existing candidates and updates them individually; plan backups, maintenance time and a rollback/restore procedure before applying it to any non-development database. A malformed, overlong or inconsistent index is excluded or stops the current candidate's comparison; sequential review also rejects a mismatch. Other stale/missing indexes can hide rows without detection, including `ProductPresentation` indexes, because ordinary direct writes, bulk operations and SQL can bypass the controlled intake. The cap bounds application inspection, not all database sorting/scan work; no production-scale benchmark exists. Comparisons are recomputed on viewing, are not saved in review snapshots and are not rechecked when a review is submitted. Concurrent changes, database collation, stale indexes and differing identifier semantics can change results. A reviewer must not use this feature as an approval or complete reconciliation, and no claim of source access or validation follows from a displayed record.
