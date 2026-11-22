# DarooBank | داروبانک

DarooBank is planned as a Persian-first pharmaceutical knowledge and Iranian product/price intelligence platform. Clinical review, traceable evidence, product-level identity and verifiable price provenance are essential. It is **not an online pharmacy**.

## Current state

The repository now has an early **development-only Django vertical slice**: Persian RTL home, search, about and price-status pages; a versioned read-only search endpoint; and a source-backed product-presentation model. The database starts empty. There are no verified clinical monographs, prices, ingestion, user accounts, review workflow or production deployment. The publication flag is a technical filter, **not** a complete clinical/data governance workflow. No source rights have been established. Do not deploy to production without explicit authorization and security/clinical review.

## Run locally

Python 3.11+ is required. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DAROOBANK_DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py runserver 127.0.0.1:8000
.venv/bin/python manage.py test
```

The local SQLite database and `.env` are ignored by Git. `.env.example` is documentation only; export its variables in the shell (Django does not load it automatically). Development settings are not production-ready. See [development guide](docs/DEVELOPMENT_GUIDE.md) and [implementation changelog](docs/CHANGELOG.md).

## Documentation

- [Implementation changelog](docs/CHANGELOG.md) · [Gap analysis](docs/GAP_ANALYSIS.md) · [Resource review](docs/RESOURCE_REVIEW.md) · [Design system](docs/DESIGN_SYSTEM.md)
- [Assessment and repository audit](docs/ASSESSMENT.md) · [Project overview](docs/PROJECT_OVERVIEW.md) · [Product requirements](docs/PRODUCT_REQUIREMENTS.md)
- [System architecture](docs/SYSTEM_ARCHITECTURE.md) · [Technology decisions](docs/TECH_STACK_DECISIONS.md) · [Decision records](docs/ARCHITECTURE_DECISIONS/README.md)
- [Database schema](docs/DATABASE_SCHEMA.md) · [ER diagram](docs/ERD.md) · [API design](docs/API_DESIGN.md)
- [Crawler architecture](docs/CRAWLER_ARCHITECTURE.md) · [Data sources](docs/DATA_SOURCES.md) · [Price model](docs/PRICE_DATA_MODEL.md)
- [Clinical content standards](docs/CLINICAL_CONTENT_STANDARDS.md) · [Security](docs/SECURITY.md)
- [Deployment](docs/DEPLOYMENT.md) · [Development guide](docs/DEVELOPMENT_GUIDE.md) · [Testing](docs/TESTING_STRATEGY.md) · [Operations](docs/OPERATIONS_RUNBOOK.md) · [Roadmap](docs/ROADMAP.md)
