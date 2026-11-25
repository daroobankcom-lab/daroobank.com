"""Small, non-sensitive GitHub annotation for the isolated browser smoke test.

Full failure output still goes to the ordinary test log. Never copy arbitrary
subprocess output, URLs, environment variables or assertion values into the
annotation, which is visible separately from the log.
"""
import json
import math
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
_SKIP_MESSAGES.update({
    f'skip {page} {width}: {phase} ({region})': (page, width, f'{phase}: {region}')
    for page in ('home', 'about', 'login', 'forced-home', 'forced-login') for width in (320, 390, 768, 1440)
    for phase in ('main focus', 'next focus')
    for region in ('none', 'expected', 'skip', 'main', 'body', 'header', 'footer', 'other-main', 'other')
})


def _focus_failure(stderr):
    for line in stderr.splitlines():
        for prefix in ('AssertionError [ERR_ASSERTION]: ', 'AssertionError: '):
            if line.startswith(prefix):
                return _FOCUS_MESSAGES.get(line[len(prefix):])
    return None


def _skip_visibility_failure(message):
    """Classify a known skip assertion without echoing its untrusted JSON."""
    label, separator, payload = message.partition(': visible focus ')
    if not separator or len(payload) > 2048:
        return None
    known = _SKIP_MESSAGES.get(label + ': visible focus')
    if not known:
        return None
    try:
        state = json.loads(payload)
    except (ValueError, RecursionError):
        return None
    numbers = ('opacity', 'width', 'height', 'top', 'bottom', 'left', 'right', 'viewportWidth', 'viewportHeight')
    if (not isinstance(state, dict) or set(state) != set(numbers) | {'focusVisible', 'visibility', 'display'}
            or type(state['focusVisible']) is not bool
            or state['visibility'] not in ('visible', 'hidden', 'collapse')
            or state['display'] not in ('none', 'inline', 'block', 'inline-block', 'flex', 'inline-flex',
                                        'grid', 'inline-grid', 'contents', 'flow-root', 'table', 'inline-table',
                                        'list-item', 'ruby')
            or any(type(state[key]) not in (int, float) or abs(state[key]) > 1_000_000_000
                   or not math.isfinite(state[key]) for key in numbers)):
        return None
    reasons = []
    if not state['focusVisible']: reasons.append('focus indicator')
    if state['visibility'] != 'visible' or state['display'] == 'none': reasons.append('hidden style')
    if state['opacity'] <= 0: reasons.append('transparent')
    if state['width'] <= 0 or state['height'] <= 0: reasons.append('empty bounds')
    # Report only a fixed side and coarse distance, never raw geometry. This
    # distinguishes tiny rounding from a displaced element in CI annotations.
    overflows = (('top', -state['top']), ('bottom', state['bottom'] - state['viewportHeight']),
                 ('left', -state['left']), ('right', state['right'] - state['viewportWidth']))
    outside = []
    for side, distance in overflows:
        if distance > 0:
            bucket = '<1px' if distance < 1 else '1–8px' if distance <= 8 else '>8px'
            outside.append(f'{side} {bucket}')
    if outside:
        reasons.append('outside viewport: ' + ', '.join(outside))
    return (known[0], known[1], 'visible focus: ' + ', '.join(reasons)) if reasons else None


def _skip_failure(stderr):
    for line in stderr.splitlines():
        for prefix in ('AssertionError [ERR_ASSERTION]: ', 'AssertionError: '):
            if line.startswith(prefix):
                message = line[len(prefix):]
                return _SKIP_MESSAGES.get(message) or _skip_visibility_failure(message)
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
