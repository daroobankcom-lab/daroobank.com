"""Synthetic-only tests for the explicit local projection-repair tool."""
import base64
import io
import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.core import signing
from django.core.management import CommandError, call_command
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings

from .models import ProductPresentation
from .normalization import normalize_search
from .projection_repair import (MAX_PK, MAX_SEARCH_LENGTH, SALT, ProjectionRepairError,
                                apply_projection, preview_projection)
from .quality import inspect_batch
from .services import search_product_page
from pricing.importer import suggest_product


@override_settings(DEBUG=True, SECRET_KEY='synthetic-test-secret-key')
class ProjectionRepairTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده خصوصی ساختگی', name_en='Synthetic fixture', manufacturer='شرکت فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='۰۰۱',
            source_name='منبع خصوصی ساختگی', source_url='https://example.org/private-synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True)

    def damage(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='۰۰۲', strength='20 mg')

    def preview(self):
        return preview_projection(presentation_id=self.product.pk)

    def apply(self, token):
        return apply_projection(presentation_id=self.product.pk, token=token, synthetic_confirmed=True)

    def test_preview_is_read_only_private_and_repair_only_changes_projections(self):
        self.damage()
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        plan = self.preview()
        self.assertEqual((plan['status'], plan['fields']), ('needs_repair', ['search_text', 'irc_normalized']))
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        body = json.dumps(plan, ensure_ascii=False)
        decoded = base64.urlsafe_b64decode(plan['token'].split(':')[0] + '===').decode()
        for secret in ('فرآورده خصوصی ساختگی', 'منبع خصوصی', 'private-synthetic', '۰۰۲', '20 mg'):
            self.assertNotIn(secret, body)
            self.assertNotIn(secret, decoded)
        self.assertEqual(self.apply(plan['token']), {'id': self.product.pk, 'status': 'repaired', 'fields': plan['fields']})
        after = ProductPresentation.objects.values().get(pk=self.product.pk)
        self.assertEqual({k: v for k, v in after.items() if k not in plan['fields']},
                         {k: v for k, v in before.items() if k not in plan['fields']})
        self.assertEqual(after['irc_normalized'], '002')
        self.assertIn(normalize_search('20 mg'), after['search_text'])
        self.assertEqual(self.preview(), {'id': self.product.pk, 'status': 'consistent', 'fields': []})
        with self.assertRaises(ProjectionRepairError): self.apply(plan['token'])
        self.assertNotIn('irc_projection', inspect_batch()['rows'][0]['issues'])

    def test_search_and_price_match_can_change_after_repair(self):
        self.damage()
        match = dict(irc='002', manufacturer='شرکت فرضی', strength='20 mg', dosage_form='قرص', package_description='10 عدد')
        self.assertEqual(suggest_product(match), ('unmatched', None))
        self.assertEqual(search_product_page('002')[0], [])
        self.apply(self.preview()['token'])
        status, product = suggest_product(match)
        self.assertEqual((status, product.pk), ('suggested', self.product.pk))
        self.assertEqual([p.pk for p in search_product_page('002')[0]], [self.product.pk])

    def test_single_projection_drift_and_blank_irc(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc_normalized='wrong')
        plan = self.preview()
        self.assertEqual(plan['fields'], ['irc_normalized'])
        self.assertEqual(self.apply(plan['token'])['fields'], ['irc_normalized'])
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='', irc_normalized='wrong')
        plan = self.preview()
        self.assertEqual(plan['fields'], ['search_text', 'irc_normalized'])
        self.apply(plan['token'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.irc_normalized, '')

    def test_stale_after_source_projection_or_publication_change(self):
        for changes in [dict(name_fa='نام تغییر یافته'), dict(source_url='https://example.org/changed'),
                        dict(search_text='another projection'), dict(published=False), dict(verified_at=None)]:
            with self.subTest(changes=changes):
                self.damage()
                plan = self.preview()
                ProductPresentation.objects.filter(pk=self.product.pk).update(**changes)
                before = ProductPresentation.objects.values().get(pk=self.product.pk)
                with self.assertRaises(ProjectionRepairError): self.apply(plan['token'])
                self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
                ProductPresentation.objects.filter(pk=self.product.pk).update(
                    name_fa='فرآورده خصوصی ساختگی', source_url='https://example.org/private-synthetic',
                    search_text='deliberately stale', published=True,
                    verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))

    def test_verified_timestamp_microsecond_change_invalidates_preview(self):
        self.damage()
        ProductPresentation.objects.filter(pk=self.product.pk).update(
            verified_at=datetime(2026, 1, 1, microsecond=123001, tzinfo=timezone.utc))
        plan = self.preview()
        ProductPresentation.objects.filter(pk=self.product.pk).update(
            verified_at=datetime(2026, 1, 1, microsecond=123002, tzinfo=timezone.utc))
        with self.assertRaises(ProjectionRepairError): self.apply(plan['token'])

    def test_invalid_identity_is_skipped_without_echo_or_writes(self):
        for changes in [dict(name_fa='\x01secret'), dict(manufacturer='\u200c'), dict(irc='ﬃ' * 40),
                        dict(search_text='x' * (MAX_SEARCH_LENGTH + 1))]:
            with self.subTest(changes=changes):
                ProductPresentation.objects.filter(pk=self.product.pk).update(**changes)
                before = ProductPresentation.objects.values().get(pk=self.product.pk)
                result = self.preview()
                self.assertEqual(result['status'], 'unsafe')
                self.assertNotIn('token', result)
                self.assertNotIn('secret', json.dumps(result))
                self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
                ProductPresentation.objects.filter(pk=self.product.pk).update(
                    name_fa='فرآورده خصوصی ساختگی', manufacturer='شرکت فرضی', irc='۰۰۱', search_text='stale')

    def test_invalid_and_wrong_id_tokens_are_rejected(self):
        self.damage()
        plan = self.preview()
        tokens = ['', '.', 'x' * 513, plan['token'] + 'x', None,
                  signing.dumps({'id': self.product.pk, 'state': '0' * 64, 'database': '0' * 64, 'extra': True}, salt=SALT),
                  signing.dumps({'id': True, 'state': '0' * 64, 'database': '0' * 64}, salt=SALT)]
        for token in tokens:
            with self.subTest(token=token), self.assertRaises(ProjectionRepairError): self.apply(token)
        with self.assertRaises(ProjectionRepairError):
            apply_projection(presentation_id=self.product.pk + 1, token=plan['token'], synthetic_confirmed=True)
        for value in (True, 0, -1, MAX_PK + 1, '1', None):
            with self.subTest(value=value), self.assertRaises(ProjectionRepairError):
                preview_projection(presentation_id=value)
        with self.assertRaises(ProjectionRepairError): preview_projection(presentation_id=MAX_PK)

    def test_apply_requires_explicit_boolean_synthetic_attestation(self):
        self.damage()
        token = self.preview()['token']
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        for confirmation in (False, 1, 'yes', None):
            with self.subTest(confirmation=confirmation), self.assertRaises(ProjectionRepairError):
                apply_projection(presentation_id=self.product.pk, token=token, synthetic_confirmed=confirmation)
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        self.assertEqual(self.apply(token)['status'], 'repaired')

    def test_expired_and_database_bound_tokens_fail(self):
        self.damage()
        with patch('django.core.signing.time.time', return_value=1_000_000):
            token = self.preview()['token']
        with patch('django.core.signing.time.time', return_value=1_000_601):
            with self.assertRaises(ProjectionRepairError): self.apply(token)
        with patch('django.core.signing.time.time', return_value=1_000_999):
            future = self.preview()['token']
        with patch('django.core.signing.time.time', return_value=1_000_000):
            with self.assertRaises(ProjectionRepairError): self.apply(future)
        token = self.preview()['token']
        with patch('catalog.projection_repair._database_digest', return_value='f' * 64):
            with self.assertRaises(ProjectionRepairError): self.apply(token)

    def test_delete_after_preview_fails_closed(self):
        self.damage()
        token = self.preview()['token']
        self.product.delete()
        with self.assertRaises(ProjectionRepairError): self.apply(token)

    def test_exception_after_database_update_rolls_back(self):
        self.damage()
        token = self.preview()['token']
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        original = QuerySet.update
        def update_then_fail(query, **kwargs):
            original(query, **kwargs)
            raise RuntimeError('synthetic write failure')
        with patch.object(QuerySet, 'update', update_then_fail):
            with self.assertRaisesRegex(RuntimeError, 'synthetic write failure'): self.apply(token)
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        self.assertEqual(self.apply(token)['status'], 'repaired')

    def test_cli_preview_commit_and_fail_closed_flags(self):
        self.damage()
        out = io.StringIO()
        call_command('repair_catalog_projection', presentation_id=self.product.pk, stdout=out)
        plan = json.loads(out.getvalue())
        self.assertEqual(plan['status'], 'needs_repair')
        for options in (dict(commit=True), dict(token=plan['token']),
                        dict(commit=True, token=plan['token']), dict(confirm_synthetic=True)):
            with self.subTest(options=options), self.assertRaises(CommandError):
                call_command('repair_catalog_projection', presentation_id=self.product.pk, **options)
        out = io.StringIO()
        call_command('repair_catalog_projection', presentation_id=self.product.pk, commit=True, token=plan['token'], confirm_synthetic=True, stdout=out)
        self.assertEqual(json.loads(out.getvalue())['status'], 'repaired')
        with self.assertRaises(CommandError):
            call_command('repair_catalog_projection', presentation_id=self.product.pk, commit=True, token=plan['token'], confirm_synthetic=True)

    @override_settings(DEBUG=False)
    def test_debug_gate_at_service_and_command(self):
        for fn in (lambda: self.preview(), lambda: self.apply('invalid')):
            with self.assertRaises(ProjectionRepairError): fn()
        with self.assertRaises(CommandError):
            call_command('repair_catalog_projection', presentation_id=self.product.pk)
