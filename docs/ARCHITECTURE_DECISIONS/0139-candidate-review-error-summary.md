# ADR 0139: selected candidate review error summaries

Status: development-only server-rendered usability change, 24 November 2026. Extends the pattern of ADR 0135 to the existing product and price candidate detail/review pages.

When a review POST was invalid or stale, those long detail pages redisplayed form errors near the bottom without an error-specific page title or a top-level summary. For a permitted reviewer whose form is still available, the existing shared summary now links visible invalid fields and gives generic guidance for hidden fields and non-field errors. The title indicates an error. Errors and submitted values remain in the existing form, not duplicated in the summary. Error status codes, CSRF, permission checks, concurrency and writes are unchanged.

If an error is returned but the current detail view would not display the review form (for example, the submitter cannot review their own candidate), a fixed general notice is shown instead of links to fields that do not exist; it does not echo submitted values. This is distinct from authorization: the view's existing permission check still applies before processing the form.

Synthetic tests check normal GET, CSRF rejection, invalid visible and hidden fields, stale 409, unavailable forms, private response headers and no review writes. Selected Chromium checks use actual keyboard focus and fragment navigation to a reason field on both pages at one viewport, plus layout and automated axe checks. No automatic focus move or live announcement is added. This does not establish comprehensive screen-reader, keyboard, mobile-device or contrast accessibility; other review forms and outputs are outside this decision.
