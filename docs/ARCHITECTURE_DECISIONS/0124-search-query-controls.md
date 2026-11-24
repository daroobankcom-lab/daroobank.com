# ADR 0124: reject controls in the retained public search query

Status: development input-validation change, 24 November 2026.

## Context and decision

The public search already rejects NUL and surrogate code points in its retained query before touching the database. Other Unicode controls could previously survive in the query and appear in the HTML search field or invalid-cursor recovery page. Reject all Unicode control (`Cc`) and surrogate (`Cs`) characters in the query prefix checked by `search_product_page`, with the existing generic `invalid_query` response, before cursor validation or SQL. The HTML error leaves the search field blank; selected API/HTML GET and HEAD responses retain their privacy headers.

This is an intentionally incompatible tightening: a tab or newline *inside* a retained query is no longer treated as whitespace. HTTP views still trim the input before taking 120 characters and calling the service; therefore whitespace controls stripped from either end and characters beyond the retained prefix are not checked. The direct service checks its first 120 characters without trimming. Unicode format characters such as Persian ZWNJ remain accepted. HTTP decoding can replace invalid bytes before the application sees them. Do not assume raw queries are confidential: URLs may still reach access logs, browser history, upstream infrastructure or debug pages.

## Evidence and limitations

Synthetic service tests cover all 65 Unicode `Cc` code points, selected surrogates, precedence over a bad cursor, and prefix boundaries. HTTP tests exercise representative control characters in both endpoints and methods, selected privacy headers and no echo of a canary; Persian lookup normalization remains tested. They do not check all Unicode spoofing, proxy behavior, logs, network limits, browsers, unusual server configurations or every direct caller. This does not verify data or provide rate limiting.
