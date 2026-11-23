# ADR 0027: keyboard skip navigation and browser diagnostics

Status: development-only, 22 November 2026.

## Context

GitHub Actions run 45135591434 failed at the home skip-link next-focus assertion. Its annotation identified the source line but not width, observed element or cause; the job log could not be retrieved (EOF), and the failed job could not be rerun. A local diagnostic run observed the expected skip-link focus and `#main` fragment at all four tested widths, including the home axe audit at 390, but this does not reproduce or explain that CI failure or an older focus-outline failure.

A separate reproducible issue was identified: Django's default login form sets `autofocus` on username, potentially bypassing the page start and skip link. Removing that attribute is an accessibility change independent of the unknown CI cause.

## Decision

Use a subclass of Django's authentication form that removes username autofocus only from the instantiated staff form. Normal authentication, CSRF, redirect and privacy mechanisms are unchanged. The same applies when an invalid login is rendered. The Django base form is not modified.

The synthetic Chromium test now exercises actual Tab/Enter/Tab navigation on home, about and login at 320, 390, 768 and 1440 pixels, including login reached through a private-page redirect. It checks first focus, target, visible focus/outline and following focus inside main. It explicitly waits for the same-page `#main` URL before the next Tab and does not run axe between keyboard events; this removes two possible sources of test interference but is not proof they caused the historical failure. It tests the invalid-login response at 390 and selected home/login flows under emulated forced colors and reduced motion. Tests on separate synthetic pages deliberately break the target, tab order, visibility, fragment activation and next focus to verify these checks reject those regressions. No keyboard focus is forced for these checks; failures are not retried or ignored.

The changed test order revealed axe contrast violations on the home eyebrow and two decorative caption styles in one local run. Darken those colors; separately calculate contrast for the eyebrow and both decorative captions on their opaque backgrounds. A deliberate low-contrast mutation must fail. Automated results depend on viewport/rendering and additional inconclusive axe color-contrast items still require human evaluation.

Expand the existing CI error annotation's exact allowlist to include skip-navigation page, width and fixed phase, and focus checks on the skip link. Arbitrary output, values, URLs and paths are still not copied into the annotation; full logs may contain synthetic test values. This helps diagnose future failures but does not identify the observed historical failure's width or root cause.

## Limits

Only headless Chromium and selected synthetic flows were tested; forced colors and reduced motion are emulations, not physical devices or assistive technologies. Keyboard and visual checks are not comprehensive WCAG conformance or a screen-reader, browser interoperability, production security or clinical assessment. Browser sandbox is disabled in this isolated development test. Failed job logs and historical cause remain unavailable; later passes do not prove those failures fixed. Login deliberately no longer focuses the username automatically; users can navigate to it with the keyboard or pointer.
