"""Opt-in synthetic CMS envelope and PostgreSQL restore exercise, never production."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import skipUnless
from uuid import uuid4

from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase, override_settings

from catalog.test_identity import ALL, user
from .synthetic_restore_fixture import build_cross_domain_fixture, verify_cross_domain_fixture

ROOT = Path(__file__).resolve().parent.parent


@skipUnless(os.environ.get('DAROOBANK_ENCRYPTED_RESTORE_TESTS') == '1',
            'Optional synthetic encrypted restore drill is disabled')
@override_settings(DEBUG=True)
class SyntheticEncryptedRestoreTests(TransactionTestCase):
    def test_authenticated_envelope_then_restore_and_selected_negative_controls(self):
        # Name/setting checks are additional guards, not proof of server isolation.
        self.assertTrue(getattr(settings, 'DAROOBANK_RESTORE_ISOLATED', False))
        self.assertEqual(connection.vendor, 'postgresql')
        source = connection.settings_dict['NAME']
        self.assertRegex(source, r'^test_daroobank_restore_[0-9a-f]{32}$')
        self.assertTrue(connection.get_autocommit())
        for tool in ('pg_dump', 'pg_restore', 'openssl'):
            self.assertIsNotNone(shutil.which(tool), f'{tool} is required for this opt-in drill')

        author = user('synthetic-restore-author', *ALL)
        reviewer = user('synthetic-restore-reviewer', *ALL)
        build_cross_domain_fixture(author, reviewer)
        verify_cross_domain_fixture()

        config = connection.settings_dict
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TMPDIR') if key in os.environ}
        env.update(DAROOBANK_DEBUG='1', POSTGRES_DB=source, POSTGRES_HOST=str(config['HOST']),
                   POSTGRES_PORT=str(config['PORT']), POSTGRES_USER=str(config['USER']),
                   PGHOST=str(config['HOST']), PGPORT=str(config['PORT']), PGUSER=str(config['USER']), PGDATABASE=source)
        if config.get('PASSWORD'):
            env['POSTGRES_PASSWORD'] = str(config['PASSWORD'])
            env['PGPASSWORD'] = str(config['PASSWORD'])
        if config.get('OPTIONS', {}).get('sslmode'):
            env['POSTGRES_SSLMODE'] = str(config['OPTIONS']['sslmode'])
            env['PGSSLMODE'] = str(config['OPTIONS']['sslmode'])

        def run(args, *, child_env=env):
            # No command output is printed: DB diagnostics may contain sensitive metadata.
            return subprocess.run(args, cwd=ROOT, env=child_env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)

        target = f'test_daroobank_restore_target_{uuid4().hex}'
        self.assertRegex(target, r'^test_daroobank_restore_target_[0-9a-f]{32}$')
        self.assertNotEqual(target, source)
        created = False
        try:
            with tempfile.TemporaryDirectory(prefix='daroobank-synthetic-cms-') as directory:
                self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)
                root = Path(directory)

                def private_file(name):
                    path = root / name
                    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    os.close(fd)
                    return path

                key, cert = private_file('key.pem'), private_file('cert.pem')
                other_key, other_cert = private_file('other-key.pem'), private_file('other-cert.pem')
                archive, encrypted = private_file('source.dump'), private_file('archive.cms')
                decrypted, tampered = private_file('decrypted.dump'), private_file('tampered.cms')
                rejected_output = private_file('rejected.dump')
                forged, forged_encrypted = private_file('forged.bin'), private_file('forged.cms')
                forged_output = private_file('forged-output.bin')

                for private_key, certificate in ((key, cert), (other_key, other_cert)):
                    generated = run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1',
                                     '-subj', '/CN=synthetic-only', '-keyout', str(private_key), '-out', str(certificate)])
                    self.assertEqual(generated.returncode, 0, 'Synthetic key generation failed')
                    self.assertEqual(stat.S_IMODE(private_key.stat().st_mode), 0o600)
                dumped = run(['pg_dump', '--no-password', '--format=custom', '--no-owner', '--no-acl', '--file', str(archive)])
                self.assertEqual(dumped.returncode, 0, 'Synthetic dump failed')
                self.assertGreater(archive.stat().st_size, 128)
                encrypt = ['openssl', 'cms', '-encrypt', '-binary', '-aes-256-gcm', '-outform', 'DER']
                result = run([*encrypt, '-in', str(archive), '-out', str(encrypted), str(cert)])
                self.assertEqual(result.returncode, 0, 'Synthetic CMS encryption failed')
                info = run(['openssl', 'cms', '-cmsout', '-print', '-inform', 'DER', '-in', str(encrypted)])
                self.assertEqual(info.returncode, 0, 'Synthetic CMS inspection failed')
                self.assertIn(b'authEnvelopedData', info.stdout)
                self.assertIn(b'aes-256-gcm', info.stdout.lower())

                contents = bytearray(encrypted.read_bytes())
                self.assertGreater(len(contents), 64)
                contents[-1] ^= 1
                tampered.write_bytes(contents)
                decrypt = ['openssl', 'cms', '-decrypt', '-binary', '-inform', 'DER']
                bad = run([*decrypt, '-in', str(tampered), '-recip', str(cert), '-inkey', str(key),
                           '-out', str(rejected_output)])
                self.assertNotEqual(bad.returncode, 0, 'Tampered synthetic envelope was accepted')
                wrong_key = run([*decrypt, '-in', str(encrypted), '-recip', str(other_cert), '-inkey', str(other_key),
                                 '-out', str(rejected_output)])
                self.assertNotEqual(wrong_key.returncode, 0, 'Wrong synthetic key was accepted')
                # Failed decryption may leave plaintext in its output file. Never
                # use rejected_output as input to pg_restore, even if it exists.
                restored_archive = run([*decrypt, '-in', str(encrypted), '-recip', str(cert), '-inkey', str(key),
                                        '-out', str(decrypted)])
                self.assertEqual(restored_archive.returncode, 0, 'Synthetic CMS decryption failed')
                self.assertEqual(decrypted.read_bytes(), archive.read_bytes())
                self.assertEqual(run(['pg_restore', '--list', str(decrypted)]).returncode, 0)

                # Simulate a different, valid archive encrypted using only the
                # public certificate. Encryption does not establish backup origin.
                with connection.cursor() as cursor:
                    cursor.execute('CREATE TABLE synthetic_replacement_only (value integer NOT NULL)')
                    cursor.execute('INSERT INTO synthetic_replacement_only VALUES (246)')
                forged_dump = run(['pg_dump', '--no-password', '--format=custom', '--no-owner', '--no-acl',
                                   '--file', str(forged)])
                self.assertEqual(forged_dump.returncode, 0, 'Synthetic replacement dump failed')
                self.assertNotEqual(forged.read_bytes(), archive.read_bytes())
                self.assertEqual(run([*encrypt, '-in', str(forged), '-out', str(forged_encrypted), str(cert)]).returncode, 0)
                replacement = run([*decrypt, '-in', str(forged_encrypted), '-recip', str(cert), '-inkey', str(key),
                                   '-out', str(forged_output)])
                self.assertEqual(replacement.returncode, 0)
                self.assertEqual(forged_output.read_bytes(), forged.read_bytes())
                self.assertEqual(run(['pg_restore', '--list', str(forged_output)]).returncode, 0)

                with connection.cursor() as cursor:
                    cursor.execute(f'CREATE DATABASE {connection.ops.quote_name(target)}')
                created = True
                restore = run(['pg_restore', '--no-password', '--exit-on-error', '--single-transaction', '--no-owner',
                               '--no-acl', '--dbname', target, str(decrypted)])
                self.assertEqual(restore.returncode, 0, 'Synthetic decrypted restore failed')
                target_env = {**env, 'POSTGRES_DB': target, 'PGDATABASE': target}
                script = ('from daroobank.synthetic_restore_fixture import verify_cross_domain_fixture; '
                          'verify_cross_domain_fixture()')
                check = run([sys.executable, 'manage.py', 'shell', '-c', script], child_env=target_env)
                self.assertEqual(check.returncode, 0, 'Synthetic restored fixture verification failed')
                migrations = run([sys.executable, 'manage.py', 'migrate', '--check'], child_env=target_env)
                self.assertEqual(migrations.returncode, 0, 'Synthetic restored migration check failed')
                probe = connection.copy(alias='synthetic_encrypted_restore_probe')
                probe.settings_dict['NAME'] = target
                try:
                    with probe.cursor() as cursor:
                        cursor.execute("SELECT to_regclass('public.synthetic_replacement_only')")
                        self.assertIsNone(cursor.fetchone()[0])
                finally:
                    probe.close()
            verify_cross_domain_fixture()  # The source fixture remains accessible.
        finally:
            if created:
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP DATABASE {connection.ops.quote_name(target)}')
