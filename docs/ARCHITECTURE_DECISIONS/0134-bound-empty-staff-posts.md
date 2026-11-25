# ADR 0134: bind empty staff POSTs

Status: development-only form feedback, 24 November 2026.

Six staff create/revision/reference/upload views used `request.POST or None`. An authorized POST with a valid CSRF header but no form fields produced an empty `QueryDict`, so the form was unbound and silently redisplayed without required-field errors. No write occurred. Ordinary browser submissions generally include a CSRF form field, but header-token clients can submit an empty body.

These views now bind `request.POST` and, where appropriate, `request.FILES` based on the request method rather than truthiness. GET remains unbound. Invalid submissions keep the existing HTTP status and privacy behavior; this is a user-feedback change, not a change to permissions, CSRF enforcement, successful writes or database constraints.

Synthetic PostgreSQL HTTP tests use a CSRF-enforcing client, verify missing-token rejection, an unbound GET and a header-authorized empty POST for each selected view, and check required field errors and absence of selected new records. Other routes, payload formats and browser or assistive-technology behavior are not exhaustively tested.
