"""Narrow public-read privilege probe on a disposable PostgreSQL cluster."""
from uuid import uuid4

from django.db import DatabaseError, connection, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import ProductPresentation


class PublicReadRoleTests(TransactionTestCase):
    def test_selected_public_reads_work_without_write_or_account_table_access(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Role probe requires a disposable PostgreSQL superuser')
        product = ProductPresentation.objects.create(
            name_fa='محصول ساختگی دسترسی', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='001', source_name='منبع ساختگی',
            source_url='https://example.org/synthetic', verified_at=timezone.now(), published=True)
        unpublished = ProductPresentation.objects.create(
            name_fa='محصول منتشرنشده ساختگی', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', source_name='منبع ساختگی',
            source_url='https://example.org/unpublished', published=False)
        role = connection.ops.quote_name('daroobank_public_' + uuid4().hex)
        table = connection.ops.quote_name(ProductPresentation._meta.db_table)
        user_table = connection.ops.quote_name('auth_user')
        database = connection.ops.quote_name(connection.settings_dict['NAME'])
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
                cursor.execute('REVOKE CREATE ON SCHEMA public FROM PUBLIC')
                cursor.execute(f'REVOKE TEMPORARY ON DATABASE {database} FROM PUBLIC')
                cursor.execute(f'REVOKE ALL ON TABLE {table}, {user_table} FROM PUBLIC')
                cursor.execute(f'GRANT USAGE ON SCHEMA public TO {role}')
                cursor.execute(f'GRANT SELECT ON TABLE {table} TO {role}')
                cursor.execute(f'SET LOCAL ROLE {role}')
            client = Client()
            search = client.get(reverse('search_api'), {'q': 'محصول ساختگی دسترسی'})
            self.assertEqual(search.status_code, 200)
            self.assertEqual([row['id'] for row in search.json()['data']], [product.pk])
            detail = client.get(reverse('presentation_api', args=[product.pk]))
            self.assertEqual(detail.status_code, 200)
            self.assertEqual(detail.json()['data']['id'], product.pk)
            for url, query in ((reverse('search'), {'q': 'محصول ساختگی دسترسی'}),
                               (reverse('presentation_detail', args=[product.pk]), {})):
                page = client.get(url, query)
                self.assertContains(page, 'محصول ساختگی دسترسی', status_code=200)
            self.assertEqual(client.get(reverse('presentation_api', args=[unpublished.pk])).status_code, 404)
            # The HTTP filter is not a database row-security policy: this role
            # can still read an unpublished row directly using table-wide SELECT.
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT name_fa FROM {table} WHERE id = %s', [unpublished.pk])
                self.assertEqual(cursor.fetchone(), ('محصول منتشرنشده ساختگی',))
            for sql in (f'UPDATE {table} SET name_fa = %s WHERE id = %s',
                        f'SELECT count(*) FROM {user_table}',
                        'CREATE TABLE synthetic_public_role_probe (id integer)',
                        'CREATE TEMP TABLE synthetic_public_role_temp_probe (id integer)'):
                params = ['تغییر ساختگی', product.pk] if sql.startswith('UPDATE ') else []
                with self.subTest(operation=sql.split()[0]):
                    with self.assertRaises(DatabaseError) as error, transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(sql, params)
                    self.assertEqual(getattr(error.exception.__cause__, 'sqlstate', None), '42501')
            transaction.set_rollback(True)  # Roll back role, grants and schema privilege changes.
        product.refresh_from_db()
        self.assertEqual(product.name_fa, 'محصول ساختگی دسترسی')
