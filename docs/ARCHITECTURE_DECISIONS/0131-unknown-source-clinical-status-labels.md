# ADR 0131: distinguish unknown source and clinical review statuses

Status: development-only defensive display, 24 November 2026. Follows ADR 0130.

Source-claim and clinical-draft queues also mapped an unrecognized latest review to `without review`. The related-source hints on product and price detail pages did the same. These selected templates now distinguish known decisions, no decision and an unknown non-null decision with a fixed invalid label; raw unknown status text is not displayed there. Filters and source-hint membership are unchanged. A null latest decision remains ambiguous between absence and a bypass-written null. The clinical detail's separate source hints do not show review decisions at all.

Source and clinical detail histories already classify an invalid review and suppress selected details rather than labeling it `defer`; this change does not alter that classifier, validate all history or prevent subsequent review writes. It does not establish clinical validity, rights, authorization or a transactionally consistent view.

Synthetic PostgreSQL tests temporarily remove only the two named decision checks in a guarded isolated transaction, write unknown values, and check both queues, one related-source hint and the selected detail-history behavior, including private headers and no status-canary echo. A savepoint rollback check restores the two constraints. This is not authority or a safe procedure for real databases, and tests do not cover every missing constraint, null, race, route, browser or history field.
