"""Compare checked-in lock hashes with current PyPI release metadata, read-only.

This is deliberately not a general pip requirements parser or an authenticity
check. It accepts the multiline, exact-pin lock format used by this project.
"""
import json
import re
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent
LOCKS = (ROOT / 'requirements.txt', ROOT / 'requirements-build.txt')
HEADER = re.compile(
    r'^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[A-Za-z0-9_,.-]+\])?'
    r'==([A-Za-z0-9][A-Za-z0-9_.+-]*)(?:\s*;\s*[^\\]+)?\s+\\$'
)
HASH = re.compile(r'^--hash=sha256:([0-9a-f]{64})(\s+\\)?$')
MAX_METADATA_BYTES = 4 * 1024 * 1024


def canonical(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def parse_lock(text):
    """Return (name, version, hashes); reject ambiguous or incomplete input."""
    records = []
    seen = set()
    current = None
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            if current is not None:
                raise ValueError(f'Unexpected blank or comment in requirement at line {number}')
            continue
        if current is None:
            match = HEADER.fullmatch(line)
            if not match:
                raise ValueError(f'Invalid lock header at line {number}')
            name, version = match.groups()
            key = canonical(name)
            if key in seen:
                raise ValueError(f'Duplicate lock package: {name}')
            seen.add(key)
            current = (name, version, set())
        else:
            match = HASH.fullmatch(line)
            if not match:
                raise ValueError(f'Invalid hash at line {number}')
            digest, continuation = match.groups()
            if digest in current[2]:
                raise ValueError(f'Duplicate hash at line {number}')
            current[2].add(digest)
            if not continuation:
                records.append(current)
                current = None
    if current is not None:
        raise ValueError('Incomplete requirement at end of lock')
    if not records:
        raise ValueError('Lock is empty')
    return records


def fetch_release(name, version):
    # Header parsing restricts the URL components to safe package/version chars.
    url = f'https://pypi.org/pypi/{name}/{version}/json'
    with urlopen(url, timeout=20) as response:
        payload = response.read(MAX_METADATA_BYTES + 1)
    if len(payload) > MAX_METADATA_BYTES:
        raise ValueError(f'Metadata too large for {name}=={version}')
    return json.loads(payload)


def release_hashes(data, name, version):
    try:
        info, files = data['info'], data['urls']
        if (not isinstance(info['name'], str) or canonical(info['name']) != canonical(name)
                or info['version'] != version or not isinstance(files, list) or not files):
            raise ValueError('Unexpected release identity or empty release')
        result = set()
        for item in files:
            digest = item['digests']['sha256']
            if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('Invalid release hash')
            result.add(digest)
        return result
    except (KeyError, TypeError) as exc:
        raise ValueError('Malformed release metadata') from exc


def compare(records, fetch=fetch_release):
    mismatches = []
    for name, version, locked in records:
        published = release_hashes(fetch(name, version), name, version)
        missing = published - locked
        extra = locked - published
        if missing or extra:
            mismatches.append((name, version, missing, extra))
    return mismatches


def main():
    try:
        mismatch_found = False
        for path in LOCKS:
            records = parse_lock(path.read_text(encoding='utf-8'))
            mismatches = compare(records)
            print(f'{path.name}: checked {len(records)} releases')
            for name, version, missing, extra in mismatches:
                mismatch_found = True
                print(f'  {name}=={version}: {len(missing)} published hash(es) absent from lock; '
                      f'{len(extra)} locked hash(es) absent from metadata')
                for digest in sorted(missing):
                    print(f'    published-only sha256:{digest}')
                for digest in sorted(extra):
                    print(f'    lock-only sha256:{digest}')
        if mismatch_found:
            return 1
        print('Hash sets match current PyPI metadata; this does not establish authenticity or safety.')
        return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(f'Lock metadata check failed: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
