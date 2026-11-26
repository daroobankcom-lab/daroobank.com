# ADR 0183: require explicit non-debug secret and host settings

Status: fail-closed configuration guard, not authorization to deploy.

Outside debug, startup now rejects a missing `DAROOBANK_SECRET_KEY`, one shorter than 50 or longer than 512 characters, fewer than five distinct characters, non-printable/non-ASCII/space characters, and Django's `django-insecure-` prefix. This is a shape check only: a predictable repeated string can pass. Generate a unique cryptographically random key using an approved secret-management process and do not commit, log or reuse it. Rotation invalidates existing signatures and sessions unless a separately reviewed rotation policy is implemented; no such policy is supplied here.

Non-debug startup also requires an explicit, nonempty comma-separated `DAROOBANK_ALLOWED_HOSTS` list. Entries must be valid ASCII DNS labels (internationalized domains supplied as IDNA/punycode) or bracketed IPv6 addresses, optionally a leading dot for an explicitly trusted DNS domain and its subdomains. Wildcard `*`, URLs, ports, empty entries and control characters are rejected. A leading-dot pattern trusts every subdomain and must only be used after ownership review. These checks do not resolve DNS or prove domain ownership. They do not configure proxy headers, CSRF origins, TLS, HSTS, firewall policy or hostname routing.

Development retains its previous local and `.e2b.app` preview behavior. Existing non-debug environments using short, insecurely prefixed, non-ASCII or whitespace-containing secrets, implicit/empty hosts, wildcard hosts or URL/port entries must be corrected before startup; changing a secret has operational consequences. All error messages are generic and avoid echoing the submitted key or hosts.

Fresh-process synthetic tests cover disabled-debug startup failures, valid host patterns and non-echo, preview compatibility, Django's host boundary and the separate frame-deny/CSP behavior. The tests do not prove randomness, secret protection, proxy correctness or production security.
