# Crawler and ingestion architecture

The system includes local CSV candidate staging with development-only successful web intake summaries, and an offline, non-persistent window inspection utility, but no network source adapter, crawler, scheduler, credentials, source permissions or inspected Iranian source API exists. Apart from the explicitly described window inspection and web-intake receipt utilities, the crawler architecture below is design only. Do not operate an adapter or republish data until permission, permitted rate, scope, retention and terms are recorded and validated.

## Source discovery gate

For each source record owner/contact, rights/licence, approved fields, access method, availability, robots/terms, rate policy, auth, data use, export and change notice, permitted raw retention and verification date. With owner approval inspect public pages, page navigation, documented endpoints, response formats and pagination in a controlled browser/network session. Do not bypass login, rate limits, CAPTCHA or access controls. Capture sanitized versioned fixtures only where allowed. If discovery is blocked, use a properly authorized signed import or pursue a partnership; never infer undocumented endpoints.

## Independent lifecycle

A scheduler dispatches a single run under a DB lease/lock to a separate constrained worker, not the web process. Default intended window is **23:00–01:00 Asia/Tehran**, starting on local date D at 23:00 and ending D+1 at 01:00; store timezone-aware UTC instants and compute using IANA timezone rules for each date, not a fixed UTC offset. Settings are audited and validated; handle timezone rule changes and duplicate scheduler events. At window end stop issuing new requests, checkpoint unfinished work and mark run partial; do not call it successful. Resume only under an explicit policy and a new/linked run. Actual persisted schedule settings and controls are future admin functions, not implemented.

## Pipeline and adapter contract

1. **Collect:** authorized feed/API/export, incremental cursor or changed-since where actually supported; otherwise bounded, approved periodic full reconciliation. Timeout, retry with capped exponential backoff/jitter for transient failures, honor rate limits and `Retry-After`; do not retry permanent auth/permission errors blindly.
2. **Preserve:** source metadata, record ID/revision, content hash, run/time and restricted raw payload or a reference if permitted. Deduplicate on `(source, record identifier, revision/hash)`; securely handle and expire raw data per licence.
3. **Normalize:** explicit versioned field mappings, Unicode and declared currency/unit, preserving original values. Adapters implement `discover`, `fetch`, `parse`, `normalize`, `validate` and checkpoint semantics; source-specific fixture tests required.
4. **Match:** stable identifier with confirmed scope + maker/form/strength/pack checks; conflicting/missing fields go to manual candidate review. Similar names supply suggestions only and never merge automatically.
5. **Validate/reconcile:** duplicates, required fields, units, currency, unrealistic or suspicious change, source conflict and completeness. Thresholds are configuration backed by observed distributions and reviewers, not assumed. Store every validation result; no implicit inference from absent rows.
6. **Publish:** approval is required for new packages and configured price changes; until policies and matching are tested all changes are manually reviewed. Atomic transaction appends decision/publication/history and invalidates public cache. Failed/partial runs cannot replace a verified price, infer discontinuation or trigger bulk deactivation.
7. **Report:** complete/partial/failed/cancelled, timing, source version, pages/records expected and processed where known, candidates, approvals, anomalies, retries, checkpoint and actionable errors. Redact secrets and PHI.

## Controls and failure

Manual start, pause, resume and retry are authorized, auditable and idempotent; do not run two active jobs for one source unless a proven partitioned design exists. A source schema/pagination change, unexpectedly empty response, incomplete pagination, expired rights, format drift, excessive error rate or identity ambiguity fails closed and alerts operations; do not publish data from that affected run automatically. Full reconciliation is considered complete only with source-specific reliable coverage evidence; unknown total is not evidence of completeness. Reprocessing after a crash cannot duplicate observations or approvals. Worker failure or queue outage must leave verified data intact and public requests available.


## Implemented offline window inspection

`ingestion/schedule.py` computes the current or next half-open daily interval for a supplied aware instant, defaulting to 23:00–01:00 Asia/Tehran. Per-invocation start, end and IANA timezone are configurable; equal times are rejected. It returns local and UTC boundaries, distinguishing same-day from overnight, and rejects ambiguous or nonexistent local boundary times. It consults installed timezone data rather than assuming a fixed Tehran offset. See [ADR 0002](ARCHITECTURE_DECISIONS/0002-offline-ingestion-window.md) and the [development guide](DEVELOPMENT_GUIDE.md#offline-ingestion-window-inspection) for usage and limitations. There is no schedule persistence, rights check, scheduler, worker, network access, dispatch, run history, lock, checkpoint or publication. An open window must never be treated as authorization to operate a source.


The development `ImportReceipt` summarizes only a successful web CSV staging request; it is not a crawler run, failure report, checkpoint or batch manifest. New receipt-backed imports retain bounded row-to-candidate outcomes; earlier receipts have no backfill. CLI, direct calls to the original importer services and historical imports remain absent; the receipt wrappers themselves can also be called directly by local code. Receipt creation and candidate staging share a transaction; this is not a tamper-proof audit or a production concurrency guarantee. See [ADR 0003](ARCHITECTURE_DECISIONS/0003-web-intake-receipts.md) and [ADR 0004](ARCHITECTURE_DECISIONS/0004-intake-row-manifest.md).
