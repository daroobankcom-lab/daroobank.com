"""Create or inspect a local SQLite snapshot, without overwriting existing files.

Use only in a trusted local directory with synthetic data. A snapshot contains
all database data, including password hashes and staff records; it is not encrypted.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import stat
import sys
import time


class SnapshotError(Exception):
    pass


def _source(path):
    try:
        path = Path(path).expanduser().resolve()
        if not path.is_file():
            raise SnapshotError('Source must be an existing regular SQLite database.')
        with path.open('rb') as file:
            if file.read(16) != b'SQLite format 3\x00':
                raise SnapshotError('Source is not a SQLite database file.')
        # Explicit read-only URI prevents SQLite creating an empty source on a typo.
        return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        raise SnapshotError('Cannot open source database.') from exc


def _check(connection):
    try:
        # Do not print result rows: database contents could be sensitive.
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise SnapshotError('SQLite integrity check failed.')
        if connection.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise SnapshotError('SQLite foreign key check failed.')
    except sqlite3.Error as exc:
        raise SnapshotError('Cannot verify SQLite database.') from exc


def verify(source):
    connection = _source(source)
    try:
        _check(connection)
    finally:
        connection.close()


def snapshot(source, destination, *, deadline_seconds=30):
    """Back up source into a new private file; verify the copy before returning.

    SQLite's backup API reads a consistent committed database, including WAL data.
    The deadline is best effort and not a guarantee against blocked filesystem I/O.
    The containing directory must be trusted and local.
    """
    destination = Path(destination).expanduser()
    if destination.suffix.lower() != '.sqlite3':
        raise SnapshotError('Destination must have a .sqlite3 extension.')
    if deadline_seconds <= 0:
        raise SnapshotError('Deadline must be positive.')
    source_conn = _source(source)
    reserved = False
    identity = None
    target_conn = None
    try:
        try:
            fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except (OSError, ValueError) as exc:
            raise SnapshotError('Cannot create new destination; it must not already exist.') from exc
        reserved = True
        try:
            info = os.fstat(fd)
            identity = (info.st_dev, info.st_ino)
        finally:
            os.close(fd)
        target_conn = sqlite3.connect(str(destination), timeout=5)
        start = time.monotonic()

        def progress(status, remaining, total):
            if time.monotonic() - start > deadline_seconds:
                raise SnapshotError('Snapshot deadline exceeded.')

        source_conn.backup(target_conn, pages=128, progress=progress, sleep=0.05)
        _check(target_conn)
        target_conn.close()
        target_conn = None
        reserved = False
    except sqlite3.Error as exc:
        raise SnapshotError('SQLite snapshot failed.') from exc
    finally:
        if target_conn is not None:
            target_conn.close()
        source_conn.close()
        if reserved and identity is not None:
            try:
                info = destination.lstat()
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == identity:
                    destination.unlink()
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise SnapshotError('Snapshot failed; incomplete destination could not be removed.') from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local SQLite snapshot and verification; synthetic data only.')
    subparsers = parser.add_subparsers(dest='command', required=True)
    create = subparsers.add_parser('copy', help='Create a new verified snapshot (or isolated restore copy).')
    create.add_argument('source')
    create.add_argument('destination')
    check = subparsers.add_parser('verify', help='Verify a SQLite database without modifying its data.')
    check.add_argument('source')
    args = parser.parse_args(argv)
    try:
        if args.command == 'copy':
            snapshot(args.source, args.destination)
            print('Snapshot created and SQLite checks passed.')
        else:
            verify(args.source)
            print('SQLite checks passed.')
    except SnapshotError as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
