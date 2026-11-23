"""Fail when a direct runtime pin and the checked-in artifact lock diverge.

This intentionally accepts only this repository's simple exact-pin format. Pip
performs dependency resolution and verifies artifacts; this check is not a
full requirements parser or a supply-chain authenticity verifier.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PIN = re.compile(r'^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[([A-Za-z0-9_,.-]+)\])?==([A-Za-z0-9][A-Za-z0-9_.+-]*)(?:\s*;\s*.+)?$')


def canonical(value):
    return re.sub(r'[-_.]+', '-', value).lower()


def pins(text, *, lock):
    result = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if lock and line.startswith('--hash=sha256:'):
            continue
        if line.endswith('\\'):
            line = line[:-1].rstrip()
        match = PIN.fullmatch(line)
        if not match or (not lock and ';' in line):
            raise ValueError(f'Unsupported requirement: {line}')
        name, extras, version = match.groups()
        name = canonical(name)
        if lock and ';' in line:
            # A direct pin must not disappear under a platform marker.
            # Conditional transitive requirements may still be present.
            name = f'{name};conditional'
        if name in result:
            raise ValueError(f'Duplicate requirement: {name}')
        result[name] = (version, tuple(sorted(canonical(v) for v in extras.split(','))) if extras else ())
    return result


def verify(direct_text, lock_text):
    direct, locked = pins(direct_text, lock=False), pins(lock_text, lock=True)
    if not direct:
        raise ValueError('Direct requirements are empty')
    for name, value in direct.items():
        if locked.get(name) != value:
            raise ValueError(f'Direct requirement differs from lock: {name}')


def main():
    try:
        verify((ROOT / 'requirements.in').read_text(encoding='utf-8'),
               (ROOT / 'requirements.txt').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        print(f'Runtime lock check failed: {exc}', file=sys.stderr)
        return 1
    print('Direct runtime pins match the artifact lock.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
