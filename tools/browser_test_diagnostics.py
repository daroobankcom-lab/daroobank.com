"""Small, non-sensitive GitHub annotation for the isolated browser smoke test.

Full failure output still goes to the ordinary test log. Never copy arbitrary
subprocess output, URLs, environment variables or assertion values into the
annotation, which is visible separately from the log.
"""
import re
from itertools import islice

_STACK_LINE = re.compile(r'(?m)^\s*at [^\n]*[/\\]smoke\.cjs:(\d{1,6}):\d{1,6}\)?\s*$')


def browser_failure_annotation(returncode, stderr):
    """Summarize only a fixed error category, exit code and local source line."""
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
    return (f'::error file=tests/browser/smoke.cjs{location}::'
            f'Isolated synthetic browser test {outcome}; category: {kind}.{callers} '
            'See the job log for details.')
