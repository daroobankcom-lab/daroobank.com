"""Small, non-sensitive GitHub annotation for the isolated browser smoke test.

Full failure output still goes to the ordinary test log. Never copy arbitrary
subprocess output, URLs, environment variables or assertion values into the
annotation, which is visible separately from the log.
"""
import re
from itertools import islice

_STACK_LINE = re.compile(r'(?m)^\s*at [^\n]*[/\\]smoke\.cjs:(\d{1,6}):\d{1,6}\)?\s*$')

# Only fixed labels from smoke.cjs and fixed failure descriptions may reach a
# GitHub annotation. Unknown messages are ignored rather than copied verbatim.
_FOCUS_LABELS = frozenset({
    *(f'{name} {width}' for name in ('search', 'scan start', 'scan category', 'scan submit',
                                      'quality start', 'quality submit', 'skip home', 'skip about', 'skip login')
      for width in (320, 390, 768, 1440)),
    'login password', 'login submit', 'forced-colors search', 'forced-colors scan start',
    'forced-colors scan category', 'forced-colors scan submit', 'forced-colors source URL',
    'forced-colors acknowledgment', 'skip forced-home 390', 'skip forced-login 390',
})
_FOCUS_REASONS = {
    'not keyboard-focused': 'not keyboard-focused',
    'missing focus outline': 'outline missing',
    'outline contrast below 3:1 against container': 'outline contrast below 3:1',
}
_FOCUS_MESSAGES = {
    f'{label}: {message}': (label, reason)
    for label in _FOCUS_LABELS for message, reason in _FOCUS_REASONS.items()
}
_SKIP_MESSAGES = {
    f'skip {page} {width}: {phase}': (page, width, phase)
    for page in ('home', 'about', 'login', 'forced-home', 'forced-login') for width in (320, 390, 768, 1440)
    for phase in ('initial focus', 'target', 'visible focus', 'fragment navigation', 'next focus')
}


def _focus_failure(stderr):
    for line in stderr.splitlines():
        for prefix in ('AssertionError [ERR_ASSERTION]: ', 'AssertionError: '):
            if line.startswith(prefix):
                return _FOCUS_MESSAGES.get(line[len(prefix):])
    return None


def _skip_failure(stderr):
    for line in stderr.splitlines():
        for prefix in ('AssertionError [ERR_ASSERTION]: ', 'AssertionError: '):
            if line.startswith(prefix):
                return _SKIP_MESSAGES.get(line[len(prefix):])
    return None


def browser_failure_annotation(returncode, stderr):
    """Summarize only fixed categories/labels, exit code and local source lines."""
    if returncode is None:
        outcome = 'timed out'
    else:
        outcome = f'exited with code {int(returncode)}'
    if 'AssertionError' in stderr:
        kind = 'assertion'
    elif 'TimeoutError' in stderr or 'Timeout ' in stderr:
        kind = 'timeout'
    elif 'TargetClosedError' in stderr:
        kind = 'browser closed'
    else:
        kind = 'other or unknown'
    lines = list(islice((int(match.group(1)) for match in _STACK_LINE.finditer(stderr)
                         if int(match.group(1)) > 0), 3))
    location = f',line={lines[0]}' if lines else ''
    callers = f' Caller lines: {", ".join(map(str, lines[1:]))}.' if len(lines) > 1 else ''
    focus = _focus_failure(stderr)
    focus_note = f' Focus check: {focus[0]} ({focus[1]}).' if focus else ''
    skip = _skip_failure(stderr)
    skip_note = f' Skip link: {skip[0]} {skip[1]} ({skip[2]}).' if skip else ''
    return (f'::error file=tests/browser/smoke.cjs{location}::'
            f'Isolated synthetic browser test {outcome}; category: {kind}.{callers}{focus_note}{skip_note} '
            'See the job log for details.')
