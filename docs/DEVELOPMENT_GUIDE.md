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
- `templates/`, `static/`: server-rendered Persian pages, shared tokens and locally hosted OFL-licensed Vazirmatn font.
- `docs/`: product, decisions, source research and operational plans.

The SQLite schema and publication flag are not a complete provenance, review, audit or price workflow. There is no public editing interface. Database writes must not be used to bypass clinical and source-rights gates. Never add real credentials, private data or unlicensed source payloads to Git. More domains, PostgreSQL, independent workers and administrative approvals remain planned; see [architecture](SYSTEM_ARCHITECTURE.md).
