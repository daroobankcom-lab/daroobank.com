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
- `catalog/`: narrow presentation model, search normalization/service, read-only views and tests.
- `pricing/`: local review-only CSV candidate staging and inspection; no public prices or network crawler.
- `templates/`, `static/`: server-rendered Persian pages, shared tokens and locally hosted OFL-licensed Vazirmatn font.
- `docs/`: product, decisions, source research and operational plans.

The SQLite schema and publication flag are not a complete provenance, review, audit or price workflow. There is no public editing interface. Database writes must not be used to bypass clinical and source-rights gates. Never add real credentials, private data or unlicensed source payloads to Git. More domains, PostgreSQL, independent workers and administrative approvals remain planned; see [architecture](SYSTEM_ARCHITECTURE.md).

## Local price-candidate staging

This local operator-only tool reads an explicitly authorized UTF-8 CSV; it does not download data, publish prices, approve products or alter catalog records. The only included CSV is **synthetic** and must never be treated as Iranian market data. After migrations, try a dry run:

```sh
DAROOBANK_DEBUG=1 .venv/bin/python manage.py stage_price_csv \
  examples/price_candidates.synthetic.csv \
  --source-name 'Synthetic example only' --source-url https://example.org
```

To store an authorized file for later review, supply `--commit --attest-authorized` only when the operator has confirmed that collection and internal storage are permitted. This flag is an operator assertion, not proof of a licence and not an audit trail. Never put actual source files, patient information, credentials or private URLs into Git. `--source-url` must be HTTPS and cannot contain credentials, query parameters or a fragment. Local database and commands are not protected by an admin login; restrict access at the operating-system level. No authenticated admin interface exists.

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

The JSON output includes the original match status and a fresh current suggestion. The initial match is only a snapshot and can become stale; even a current exact match is **not verification**, does not establish IRC scope and must be independently reviewed. This command does not approve candidates. Existing candidate revisions are not changed on replay, and identical source/record/payload combinations are deduplicated. There is no review decision, audit log, official-source integration, automatic scheduler or public price publication.
