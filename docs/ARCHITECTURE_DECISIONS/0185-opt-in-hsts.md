# ADR 0185: opt-in non-debug HSTS duration

Status: optional HTTP header configuration, not an established TLS deployment or production approval.

HSTS remains off by default. In non-debug settings only, an explicitly supplied `DAROOBANK_HSTS_SECONDS` must be an ASCII integer from 0 through 31,536,000; malformed or excessive values fail startup without echo. Debug ignores the setting. Django's SecurityMiddleware emits `Strict-Transport-Security: max-age=N` only when its request is considered secure and N is positive. Subdomain inclusion and preloading remain off. An upstream proxy can independently set a header and is not controlled by this option.

Before enabling, owners must verify valid certificates, HTTPS reachability and renewal, direct and proxy scheme behavior, authorized hostnames and an incident/rollback plan for every affected host. HSTS is remembered by browsers for the chosen duration; a TLS outage can prevent access. Setting the option back to zero stops new headers but does **not** send `max-age=0` or clear a previously cached HSTS policy. A separately reviewed recovery procedure must account for existing clients and any proxy-supplied header. Do not enable merely to silence a deployment warning.

A single header does not establish end-to-end TLS, correct proxy trust, confidentiality, security monitoring or suitability for real data. Configuration tests use fresh processes and synthetic values; response tests cover direct HTTPS, trusted and untrusted forwarding, and no-header default. These do not verify a real proxy, certificate or browser cache.
