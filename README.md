# DarooBank | داروبانک

DarooBank is planned as a Persian-first pharmaceutical knowledge and Iranian product/price intelligence platform. Clinical review, traceable evidence, product-level identity and verifiable price provenance are essential. It is **not an online pharmacy**.

## Current state

The repository now has an early **development-only Django vertical slice**: Persian RTL home, search, presentation-detail, about and price-status pages; versioned read-only search and presentation-detail endpoints with a development OpenAPI contract; and a source-backed product-presentation model. The database starts empty. There is now a local, review-only CSV price-candidate staging command; it does not publish or crawl. A development-only authenticated staff portal, disabled outside debug mode, supports bounded CSV staging and preliminary independent review of both product and price candidates with separate permissions. Product candidates remain private and do not create or publish catalog entries; bounded product revision/IRC and conditional price-revision comparisons are advisory only. No accounts are created automatically. There are no verified clinical monographs or prices, automated ingestion, price approval/publication workflow or production deployment. The preliminary reviews are not a tamper-proof audit or approval. The publication flag is a technical filter, **not** a complete clinical/data governance workflow. Search has forward cursor pagination without snapshot consistency; no source rights have been established. Do not deploy to production without explicit authorization and security/clinical review.

## Run locally

Python 3.11+ and PostgreSQL are required. For a local development stack, copy `.env.example` to `.env`, replace every placeholder with local values, then run `docker compose up --build`. PostgreSQL data is kept in a named volume. The Compose stack uses the Django development server and is not production-ready.

For running Django outside containers, first start PostgreSQL and export the variables described in [the development guide](docs/DEVELOPMENT_GUIDE.md#current-local-implementation); Django does not load `.env` automatically. Then install dependencies, run `python manage.py migrate` and `python manage.py runserver`. Tests require a PostgreSQL role with permission to create and drop a separate test database. Do not put credentials or database dumps in Git.

The debug-only staff portal also contains a source-rights assertion ledger with separate review permissions. These claims are unverified, do not authorize source use, and do not enable crawling or publication; use synthetic data only. See the [development guide](docs/DEVELOPMENT_GUIDE.md#development-only-source-rights-assertions).

An [offline ingestion-window inspector](docs/DEVELOPMENT_GUIDE.md#offline-ingestion-window-inspection) calculates the default Tehran 23:00–01:00 interval or a per-request alternative. It does not save a schedule, contact sources or run a crawler.

Successful development web CSV staging also records a limited, permission-scoped [intake receipt](docs/DEVELOPMENT_GUIDE.md#development-only-csv-intake-receipts); new receipts include bounded row-to-candidate outcomes, but they are not original-file proof, source authorization or tamper-proof audit.

The debug-only [clinical drafting workspace](docs/DEVELOPMENT_GUIDE.md#development-only-clinical-draft-triage) supports synthetic statement drafts, bounded supplementary reference assertions and independent preliminary triage snapshots. It contains no reviewed clinical content and cannot approve or publish.

A private, read-only [catalog quality inspector](docs/DEVELOPMENT_GUIDE.md#development-only-catalog-quality-inspection) checks small batches for technical drift without verifying or changing data.

Use [PostgreSQL-native backups and isolated restore drills](docs/DEVELOPMENT_GUIDE.md#postgresql-backup-and-isolated-restore); basic GitHub Actions development checks use PostgreSQL. Dumps are unencrypted unless separately protected and are not a production backup solution.

## Documentation

- [Implementation changelog](docs/CHANGELOG.md) · [Gap analysis](docs/GAP_ANALYSIS.md) · [Resource review](docs/RESOURCE_REVIEW.md) · [Design system](docs/DESIGN_SYSTEM.md)
- [Assessment and repository audit](docs/ASSESSMENT.md) · [Project overview](docs/PROJECT_OVERVIEW.md) · [Product requirements](docs/PRODUCT_REQUIREMENTS.md)
- [System architecture](docs/SYSTEM_ARCHITECTURE.md) · [Technology decisions](docs/TECH_STACK_DECISIONS.md) · [Decision records](docs/ARCHITECTURE_DECISIONS/README.md)
- [Database schema](docs/DATABASE_SCHEMA.md) · [ER diagram](docs/ERD.md) · [API design](docs/API_DESIGN.md)
- [Crawler architecture](docs/CRAWLER_ARCHITECTURE.md) · [Data sources](docs/DATA_SOURCES.md) · [Price model](docs/PRICE_DATA_MODEL.md)
- [Clinical content standards](docs/CLINICAL_CONTENT_STANDARDS.md) · [Security](docs/SECURITY.md)
- [Deployment](docs/DEPLOYMENT.md) · [Development guide](docs/DEVELOPMENT_GUIDE.md) · [Testing](docs/TESTING_STRATEGY.md) · [Operations](docs/OPERATIONS_RUNBOOK.md) · [Roadmap](docs/ROADMAP.md)
