# ADR 0175: validate selected raw formulation formset management input

Status: development-only staff-form validation; no schema, authorization or identity-approval change.

## Context and decision

The synthetic formulation create and correction forms use Django management fields to determine the number of component forms and which are initial. Django's integer cleanup can accept boundary control characters; it also uses the last value of a repeated field. Before this change, synthetic CSRF-protected POSTs containing a tab or duplicate `TOTAL_FORMS` or `INITIAL_FORMS` could still create a formulation or correction when the cleaned values were otherwise valid.

Both selected component formsets now reject raw control or surrogate characters and duplicate submissions for these two management fields. An invalid formset gets a non-field error directing the user to reopen the page; no service write is attempted. Existing exact count checks and the five-form absolute maximum remain in force. Ordinary surrounding spaces, accepted localized digits, normal browser submissions and empty optional component rows remain supported. The client-provided `MIN_NUM_FORMS` and `MAX_NUM_FORMS` values are not used as authority and are outside this check.

The check applies only to these formsets, not arbitrary formsets, other fields, direct service calls or upstream logs. Hidden values remain client-controlled; this is neither authentication nor proof of identity, permission, consent, safety or source rights.

## Evidence

Synthetic unit tests cover prefixed formsets, both selected fields, controls and duplicate values, accepted values and bounded optional forms. CSRF-enforced create and correction POST tests exercise URL-encoded duplicate fields and verify no formulation, revision or component writes. The opt-in Chromium smoke submits a duplicate hidden management field at one viewport and checks the error summary; other identity workflow and optimized-Python regressions supplement these cases. They do not prove complete accessibility or security.
