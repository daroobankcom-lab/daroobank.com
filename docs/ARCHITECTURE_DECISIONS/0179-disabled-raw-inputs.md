# ADR 0179: honor disabled fields in selected raw-input checks

Status: defensive compatibility for shared development-only forms; no current workflow is made disabled by this decision.

Django's disabled form fields use server-supplied initial values and ignore submitted data. Shared raw-control/duplicate validation previously inspected request values even when a field was disabled, and duplicate values could make an otherwise unchanged formset row appear changed. The single-file duplicate check had the same issue. This could reject a future form or activate an optional row despite Django ignoring its submitted values.

The selected mixins now skip raw checks and duplicate change detection for disabled fields, including the CSV file. Enabled fields retain their existing control and duplicate rejection. This is a server-side `Field.disabled` decision, not trust in an HTML `disabled` attribute, and it does not validate initial values beyond Django's usual field cleaning. Direct services and other form fields remain outside this scope.

Synthetic unit tests use disabled initial values with raw controls, repeated submissions and multiple uploaded files, plus a mixed enabled/disabled case. Selected enabled-field, formset and workflow regressions protect existing rejection behavior.
