# ADR 0169: reject raw controls in selected staff date inputs

Status: development-only staff form behavior; no schema, stored-data or service date-rule change.

## Decision

Django's date parser strips surrounding whitespace, including some control characters; control-only optional dates may otherwise be interpreted as empty. Source claim start/end dates and clinical draft, revision and supplemental-reference dates now use the existing raw single-line control check. Affected fields receive a linked error and no write is attempted. Ordinary surrounding spaces, valid Gregorian dates and optional empty values retain their existing behavior. The rule operates on the original form value and does not change CSRF, permissions, domain date semantics or existing records.

This is a selected form-level check, not a general request-size limit, duplicate-parameter policy, validation of all date inputs or direct service callers, a source-rights decision or a clinical validation.

## Evidence

Synthetic tests cover both fields on the selected prefixed forms, boundary and control-only inputs, invalid calendar dates and ordinary whitespace. CSRF-enforced HTTP cases check private field errors and no writes for source claim, clinical creation/revision and supplemental-reference forms. Opt-in Chromium checks a crafted raw date and error summary, without claiming real-device or assistive-technology coverage.
