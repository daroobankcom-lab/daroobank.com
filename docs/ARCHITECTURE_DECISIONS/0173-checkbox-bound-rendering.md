# ADR 0173: render selected checkbox state from explicit boolean values

Status: development-only form rendering correction; no change to persisted data or authorization.

## Context and decision

The raw-value checkbox validation from ADR 0171 rejected ambiguous values and interpreted `0`, `false` and `off` as false. However, on an invalid form Django's checkbox renderer still saw the original nonempty string. It could render an explicitly false or malformed value as checked and echo it as the checkbox value. A user correcting an unrelated error could then see the wrong state or resubmit an unusable value.

The selected field now converts bound values to the same explicit boolean used by validation before rendering. Invalid input renders unchecked and is not echoed; its validation error remains. Checked values render checked with the normal browser default value, unchecked values render unchecked, and disabled fields use their initial value. The change detection and validation rules remain distinct and unchanged.

This does not prove consent or rights and does not cover arbitrary form widgets, all client behavior, keyboard/screen-reader accessibility, or upstream logging. See ADR 0171 for accepted tokens and scope.

## Evidence

Synthetic form tests cover true, false, malformed, duplicate and disabled input, and a CSRF-protected source form error confirms no write and no raw-value echo. Selected form workflows and opt-in Chromium tests supplement these checks; they are not an accessibility audit.
