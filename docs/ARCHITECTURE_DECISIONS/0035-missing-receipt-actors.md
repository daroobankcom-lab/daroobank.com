# ADR 0035: retaining receipts with missing actor accounts

Status: development-only, 22 November 2026. Narrows the receipt-actor display limitation noted in [ADR 0034](0034-missing-product-and-price-stagers.md); it does not establish receipt provenance or verify other actors.

## Problem and decision

Receipt actors are non-null protected foreign keys. A synthetic deferred-FK corruption demonstrated that the receipt listing's inner join could hide orphaned receipts while its paginator count still included them, and receipt detail returned 404. This is not the normal committed state when constraints are intact.

Remove the actor join in the domain-authorized listing and detail. After paginating, retrieve accounts for at most 20 displayed receipt actor IDs in one separate, same-database lookup, and use a separate lookup for detail. Show an explicit missing-account notice while retaining the receipt, its metadata, manifest and links under the existing permissions. An inactive or non-staff account still exists and its current username is displayed. Name existence does not prove historical identity, actor authority, receipt authenticity, source rights or data validity. The lookups do not lock rows and are not a transaction snapshot; permission filtering and cross-domain 404 behavior remain unchanged. No receipt is changed or repaired.

Manifest structure and row consistency inspection remain independent of receipt-actor existence and candidate-stager existence. Candidate detail's related-receipt clues also do not check receipt actors. These pages say so. Therefore a technical result or link can exist for an orphaned receipt; detail is where the missing current account can be seen. Each stage receipt actor can differ from a duplicate candidate's original stager. No attempt is made to authenticate either actor or infer agreement.

## Evidence and limits

Synthetic tests temporarily corrupt both product and price receipt actor FKs and restore them before transaction end, checking domain permission isolation, 404/403, privacy headers, listing counts, details, preserved links and consistent manifest status, as well as legacy receipts and escaping. Other tests cover existing inactive accounts, constant query count for a 20-item page, a second page, and a test-only same-transaction mutation after the separate lookup that demonstrates a stale displayed name. Chromium checks ordinary list/detail and warnings at four widths. This does not prove real concurrent deletion behavior or all race schedules. A page cap does not bound SQL work, bytes or execution time.

The underlying constraints, direct SQL/bulk writes, subsequent account or receipt changes, ABA, missing actors in other domains, lack of an immutable audit, and non-snapshot manifest reads remain outside this change. This is not a production-hardening, clinical, source-license or publication claim; use synthetic data only.
