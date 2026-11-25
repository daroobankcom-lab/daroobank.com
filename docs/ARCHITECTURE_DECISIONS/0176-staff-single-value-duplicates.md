# ADR 0176: reject duplicates in selected staff single-value inputs

Status: development-only staff input handling; no schema, source authorization or identity-approval change.

## Context and decision

Django normally uses the last submitted value for a single-value field. Synthetic CSRF-protected requests demonstrated that repeated source owner, clinical text/audience, review decision, upload action and optional component values could be silently collapsed and still write. Identical repetitions are also ambiguous; intermediaries may interpret them differently. This does not itself prove unauthorized access or source rights.

The existing raw-input mixins now reject duplicate values for their selected single-line and multiline fields. Selected choice fields (review decisions, upload actions, clinical audience and reference relation) join those checks. Product and price uploads also reject more than one `csv_file`. On otherwise-empty optional component forms, a duplicate selected value counts as a change even if its final value is blank, ensuring validation is not skipped. Existing whitespace, multiline and checkbox policies remain separate. Error messages are field-specific and no selected form service is called for an invalid request.

Ordinary browsers submit these fields once; non-browser clients sending duplicate keys or multiple files must update. This is not a general HTTP parameter-pollution defense: other form fields, query parameters, login, other formsets, direct service calls, upstream proxies and logs are outside the change. Field values may still be displayed on error according to existing escaped templates. Permissions, CSRF, source rights and clinical review remain separate concerns.

## Evidence

Synthetic prefixed form tests cover repeated identical/conflicting values, text, multiline, dates, numbers, choices, optimistic hashes, optional formset rows and duplicate files. CSRF-enforced HTTP tests check no write in selected source, clinical, identity and upload/review paths; normal/optimized workflow regressions and opt-in Chromium checks supplement them. These are not a complete security, accessibility or concurrency assessment.
