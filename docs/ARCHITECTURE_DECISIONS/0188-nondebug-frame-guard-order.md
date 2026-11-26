# ADR 0188: non-debug frame protection for early Django responses

Status: development-foundation hardening, not a production framing or deployment assessment.

The non-debug `XFrameOptionsMiddleware` now wraps `SecurityMiddleware` and the staff gate instead of sitting at the end of the stack. As a result, the configured `DENY` header applies to selected early HTTPS redirects and disabled-staff 404s as well as ordinary Django responses. Debug mode still omits the middleware so the existing development preview can be embedded.

Django's intentional per-view frame exemptions and explicitly set frame headers remain honored; this change does not override them or add a CSP `frame-ancestors` directive. A reverse proxy, static server, CDN or another application may set, remove or override headers independently. The setting is not authentication, cannot protect content served outside Django, and is not proof of correct browser, proxy or deployment behavior.

Fresh-process synthetic tests use the real non-debug settings and an unreachable database to check a home response, HTTPS and slash redirects, disabled-staff 404s, unknown routes, CSRF rejection and explicit view exemptions. A debug test checks that the development home page remains embeddable as before. These selected tests are not an exhaustive framing or accessibility assessment.
