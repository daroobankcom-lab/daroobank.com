# ADR 0057: current recorder presence in the source queue

Status: development-only, 23 November 2026. Extends the selected creator observations in [ADR 0033](0033-missing-source-and-clinical-creators.md).

## Decision

The private source queue separately checks current account existence for the at-most-20 source claims displayed on that page. It keeps claims with missing recorders visible and shows a fixed warning on each affected row, without rendering the missing account ID. Existing source name and owner visibility is unchanged. No date status or date count depends on account existence; the queue's review filter and pagination remain unchanged. An inactive or nonstaff existing account is not flagged as missing.

The account lookup is one additional SELECT for a nonempty page, with duplicate IDs batched; an empty page makes no account lookup. It occurs after the separate claim and pagination reads. Query/row bounds do not bound database work, bytes or duration.

## Evidence and limitations

Synthetic tests cover a deferred-FK missing recorder (restored before transaction end), private headers and permissions, an inactive existing recorder, unchanged date count, one lookup for each page, empty results, and a mocked changing observation. Chromium checks the warning's scope text in the normal queue at four widths; a missing-record case is exercised in Django rather than the browser. These are synthetic checks, not an audit or security certification.

The list and account reads are separate and unlocked, so the account may change after the check and the result is not a snapshot. Current presence does not establish historical identity, authority, activity, source rights, authenticity or correctness. Other pages, including the date inspection, have separate semantics; the writer independently rechecks current creator presence. This does not repair records, approve sources or make the site production-ready. Use only synthetic data.
