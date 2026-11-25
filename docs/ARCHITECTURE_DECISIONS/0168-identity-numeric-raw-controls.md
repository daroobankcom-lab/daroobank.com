# ADR 0168: reject raw controls in selected identity numeric fields

Status: development-only staff form input behavior, no schema or service numeric-rule change.

## Decision

Django's numeric field conversion can strip boundary whitespace, including tabs and line breaks. The staff identity workspace already rejected hidden raw controls in selected text and concurrency-token fields, but could silently accept such characters in ingredient/formulation/product IDs and component/package quantities. Populated component rows, product/formulation IDs and package IDs/quantities now use the existing raw-control form check, including quantity on package revisions. Revision forms deliberately omit the parent ID field they do not expose.

The form's field error and linked error summary identify the affected input. Plain surrounding spaces and existing localized-digit behavior remain accepted; tab/newline, other Unicode control characters and surrogates are rejected. An entirely empty optional component row remains empty, while a numeric control-only row is not saved. CSRF, permissions, formset caps, service validation, fingerprints, storage and lock behavior are unchanged. This does not cover every parameter, every direct service caller, duplicate form values or input-size limits.

## Evidence

Synthetic form tests cover selected fields, prefixes, boundaries and localized digits; CSRF-enforced HTTP tests exercise create and correction forms, field errors, private headers and no writes. An opt-in browser test submits a crafted numeric control value and checks its linked error summary; this does not substitute for physical-device or screen-reader testing.
