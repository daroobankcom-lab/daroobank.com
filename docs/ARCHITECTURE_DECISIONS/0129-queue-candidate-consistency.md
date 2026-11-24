# ADR 0129: hide inconsistent identity fields in private candidate queues

Status: development-only presentation change, 24 November 2026.

## Decision

The product and price queues previously rendered selected identity fields even if their candidate payload was inconsistent; detail pages already gate selected actions and, following ADR 0128, suppress selected invalid panels. Each queue now applies its existing domain consistency check to the up-to-20 candidates displayed on that page. If a candidate fails, the queue keeps its ID, link and historical status but replaces the identity text with a fixed warning. A consistent candidate retains its existing identity display. Price queue validation does not perform a current product suggestion lookup.

This does not change pagination, filters, historical status counts or stored records. It performs additional per-row Python validation (including bounded field parsing for a normally staged price), so page CPU cost changes. A payload already fetched from PostgreSQL can be oversized due to a bypass write; this does not bound JSON transfer or database work. Fields from source metadata, historical statuses, other pages, context objects and logs remain outside this display guard. The queue check is not a consistent snapshot or write authorization. A coherent rewrite with a recomputed unkeyed hash can pass; neither result verifies identity, source rights, price, clinical content or publication eligibility.

## Evidence

Synthetic Django tests exercise consistent and inconsistent product/price queue values, a changed derived amount, GET/HEAD privacy headers, no selected suggestion lookup, and a coherent product rewrite that still passes. A selected Chromium smoke run checks both queue warnings, absence of the synthetic identity canaries and responsive layout at four widths; automated accessibility checks still identify inconclusive contrast items requiring manual review. Existing queue permission, filter, pagination and detail tests remain relevant. These are selected cases, not proof against all corrupt values, concurrent changes, untrusted display fields, malicious database writers or accessibility issues. Do not use real or sensitive data in this development portal.
