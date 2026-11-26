"""Emit fixed-format CI annotations for synthetic unittest failure names only.

The full test log remains in the CI job log; this helper does not sanitize it.
Never put secrets or real data into the synthetic test suite.
"""
import re
import sys
from pathlib import Path

# Ignore subtest suffixes and arbitrary exception text. Accept only Python
# identifiers in the method and dotted test path, and cap annotations.
FAILURE = re.compile(r'^(FAIL|ERROR): ([A-Za-z_][A-Za-z_0-9]*) \(([A-Za-z_][A-Za-z_0-9.]*)\)(?:\s|$)')


def main(path):
    seen = set()
    with Path(path).open(encoding='utf-8', errors='replace') as log:
        for line in log:
            match = FAILURE.match(line)
            if not match:
                continue
            kind, method, test_path = match.groups()
            name = f'{test_path}.{method}'
            if len(name) > 250 or (kind, name) in seen:
                continue
            seen.add((kind, name))
            print(f'::error title=Synthetic test {kind}::{name}')
            if len(seen) == 30:
                break
    if not seen:
        print('::error title=Synthetic test failure::No parseable test name; inspect the CI job log.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Expected one test log path')
    main(sys.argv[1])
