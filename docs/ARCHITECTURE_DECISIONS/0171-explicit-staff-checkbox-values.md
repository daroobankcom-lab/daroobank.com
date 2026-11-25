# ADR 0171: explicit values for selected staff checkboxes

Status: development-only form validation; no changes to permissions, evidence, source rights or stored schema.

## Context and decision

Django's checkbox widget normally converts any nonempty value other than `true`/`false` into true, including `0`, `false ` and arbitrary text. In synthetic HTTP tests this allowed malformed acknowledgements to pass and create source, clinical and identity records; it could also make a submitted `0` source-scope claim true. Consent still cannot be established from a client-controlled request.

Selected staff form checkboxes (source claims and attestation, clinical/identity synthetic acknowledgements, and product/price upload rights attestations) now validate the raw checkbox value. Missing, empty, `off`, `false` or `0` means false; `on`, `true` or `1` means true. ASCII tokens are case-insensitive, but whitespace, unknown tokens, non-strings other than Python booleans/None, and duplicate submitted values are rejected. A required acknowledgement still must be true, and upload staging still requires rights attestation. Normal browsers submit `on` for checked and omit unchecked boxes. Non-browser clients submitting other strings must update; preview requests with malformed values are rejected too.

The bounded policy applies only to these forms, not arbitrary widgets or backend APIs. A checked value proves neither user comprehension nor authorization, source rights, synthetic content, or clinical safety. CSRF protection, permissions and all existing service checks remain separate requirements.

## Evidence

Synthetic PostgreSQL form and HTTP tests cover tokens, omission, duplicates, prefixes, change detection, three acknowledgement writes, false source scope, and both CSV staging/receipt no-write outcomes. Existing staff workflow and opt-in Chromium tests exercise ordinary submissions; these are not a security or accessibility audit.
