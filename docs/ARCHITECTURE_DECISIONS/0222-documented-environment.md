# 0222 — the environment is documented in one place per audience, and the inventory is pinned

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_environment_documentation.py` (8 tests, ~0.7 s, no database)

## Context

Configuration is the part of this project an operator touches without reading code. Fifteen
environment variables decide whether debug mode is on, which hosts are served, whether the staff
portal exists, whether health probes are reachable, whether HSTS is sent, whether a proxy header
is trusted, and how the database is reached — including whether that connection is encrypted in
transit and whether connections persist.

The fail-closed *behavior* of each is already measured: `test_nondebug_configuration.py`,
`test_hsts_configuration.py`, `test_database_configuration.py` and the readiness report of
[ADR 0217](0217-deployment-readiness-report.md). The documentation side was not measured at all,
and it had drifted in the direction that matters most:

| Document | Variables of the fifteen it named |
|---|---|
| `.env.example` | 15 — a complete development template, with a comment on each |
| `docs/DEVELOPMENT_GUIDE.md` | 11 — the ones a local operator sets by hand |
| `docs/DEPLOYMENT.md` | **6** — `DAROOBANK_SECRET_KEY`, `DAROOBANK_ALLOWED_HOSTS`, `DAROOBANK_HSTS_SECONDS`, `DAROOBANK_TRUST_PROXY_SSL_HEADER`, `DAROOBANK_TRUSTED_PROXY_CIDRS`, `DAROOBANK_HEALTH_PROBES_ENABLED` |

The deployment guide — the document an operator follows for a non-debug deployment — never
mentioned `DAROOBANK_DEBUG`, the switch that decides whether diagnostic pages are served, whether
the host and secret guards apply, whether HSTS is sent and whether the staff portal exists. It
never mentioned a single `POSTGRES_*` variable, so whether the database connection is verified
(`POSTGRES_SSLMODE`) and whether connections are persistent (`POSTGRES_CONN_MAX_AGE`) were
documented only in a development template and a development guide, both of which say they are not
production configuration.

Nothing would have noticed a sixteenth variable appearing in `settings.py` and in no document, or
a variable being removed from the code and left in the template forever.

## Decision

Add a configuration reference to `docs/DEPLOYMENT.md` covering all fifteen variables, and hold
every audience's document to the code with `daroobank/test_environment_documentation.py`. No
behavior changed.

The reference table gives, per variable: whether it is required, what a non-debug deployment is
expected to set, and what enforces it — the `settings.py` helper (`require_nondebug_secret`,
`require_nondebug_hosts`, `parse_hsts_seconds`, `require_trusted_proxy_networks`,
`required_database_setting`) or the decision record behind it. It also states that
`DJANGO_SETTINGS_MODULE` is the one variable the project only ever defaults.

The suite reads the inventory from the code rather than from a list anybody keeps: an AST scan of
every project module (migrations excluded) collects each environment name used as a literal in
`os.environ.get(...)`, `os.environ[...]`, `os.environ.setdefault(...)` or
`required_database_setting(...)`, and sorts it into four audiences by where it is read.

## Measured behavior

| Measurement | Result |
|---|---|
| Application reads | 15 variables, every one of them in `daroobank/settings.py`: 12 directly and `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_HOST` through `required_database_setting` |
| Defaults | `DJANGO_SETTINGS_MODULE` only, defaulted in `manage.py`, `daroobank/wsgi.py`, `tools/wait_for_database.py` and `catalog/test_synthetic_search_benchmark.py`; no variable is both read and defaulted |
| Opt-in test switches | 4, each read by exactly one test module: `DAROOBANK_BROWSER_TESTS`, `DAROOBANK_ENCRYPTED_RESTORE_TESTS`, `DAROOBANK_RESTORE_TESTS`, `DAROOBANK_SEARCH_BENCHMARK`; all four are documented in the development guide, the testing strategy or the CI workflow |
| Foreign environment | `GITHUB_ACTIONS`, read by `daroobank/test_browser.py`; pinned so that reading somebody else's environment is a documented event |
| `.env.example` | names exactly the 15, in both directions |
| `compose.yaml` | sets exactly 11 variables, all of them read by the code, and uses the fail-fast `${VAR:?…}` form for the four that are required — once for `DAROOBANK_SECRET_KEY`, which only the application service needs, and twice for `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD`, which the database service needs too |
| `docs/DEPLOYMENT.md` | now names all 14 variables that are not development-only; the `DAROOBANK_DEBUG` row's expectation cell says it stays unset or `0`, and the `POSTGRES_SSLMODE` row names `verify-full` |
| `docs/DEVELOPMENT_GUIDE.md` | names the 11 a local operator sets, and the two audiences together cover the whole inventory |
| Reverse direction | no `DAROOBANK_*` or `POSTGRES_*` name in the README, the four operator documents, the testing strategy, the template, the Compose file or the CI workflow is a variable the code does not read |

## Red check

Six regressions, each applied alone and reverted from `/tmp` backups:

| Regression | Failure |
|---|---|
| The `POSTGRES_SSLMODE` line deleted from `.env.example` | the template inventory lost a variable the code reads |
| A `DAROOBANK_RATE_LIMIT` sentence appended to `README.md` | the reverse-direction check named a variable nothing reads |
| `RATE_LIMIT = os.environ.get('DAROOBANK_RATE_LIMIT', '')` added to `settings.py` | the pinned read inventory failed |
| Both Compose occurrences of `${POSTGRES_PASSWORD:?…}` replaced with a `:-` default | the fail-fast check failed |
| The `DAROOBANK_DEBUG` expectation cell rewritten to "configurable per environment" | the off-marker check failed |
| `verify-full` replaced with "a mode appropriate for the network" in the `POSTGRES_SSLMODE` cell | the verified-mode check failed |

Three earlier attempts at these red checks were themselves faulty and are recorded because they
show what the suite does *not* catch by accident: filtering `.env.example` lines by prefix missed
a commented assignment; replacing only the first Compose occurrence of a variable left the second
one correct, which is why occurrences are now checked individually; and removing one off-marker
from a table row that still contained the word "off" in another column rightly did not fail, which
is why the check now reads the expectation cell rather than the whole line.

## Limits

- Names, not meaning. The suite cannot tell whether a documented default, range or warning is
  correct, whether the enforcing helper really enforces what the row claims, or whether the
  advice is safe. Two cells are read for content — the debug switch and the database TLS mode —
  and only for one marker each.
- The cell check reads the third column of a line that starts with `|` and contains the backticked
  variable name. Restructuring the table, or moving a variable into prose, changes what is
  checked; the "names every production variable" assertion still holds either way.
- The Compose parse is line-based, not YAML. An `environment:` block in list form (`- VAR=value`),
  an anchor or an extension field would not be matched — which surfaces as a failure of the pinned
  set rather than a silent pass, but it is a brittle reader.
- `.env.example` is checked by assignment lines, so a variable mentioned there only in a comment
  does not count as documented.
- Only this project's variables are inventoried. What a dependency reads from the environment —
  `PG*`, `PYTHON*`, library-specific switches — is out of scope, except the single foreign
  variable the project itself reads.
- The suite does not check that the documented values are the values CI or the Compose stack
  actually uses, beyond the required-variable form.
