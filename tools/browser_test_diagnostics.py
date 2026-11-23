"""Small, non-sensitive GitHub annotation for the isolated browser smoke test.

Full failure output still goes to the ordinary test log. Never copy arbitrary
subprocess output, URLs, environment variables or assertion values into the
annotation, which is visible separately from the log.
"""
import re

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
    match = _STACK_LINE.search(stderr)
    location = ''
    if match and int(match.group(1)) > 0:
        location = f',line={int(match.group(1))}'
    return (f'::error file=tests/browser/smoke.cjs{location}::'
            f'Isolated synthetic browser test {outcome}; category: {kind}. '
            'See the job log for details.')
