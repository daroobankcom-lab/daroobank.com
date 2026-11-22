from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .identity import (IdentityConflict, IdentityError, digest, package_snapshot, revise_package,
                       review_package, valid_package_revision)
from .models import IdentityPackageDraft, IdentityPackageReview, IdentityPackageRevision, ProductPresentation
from .test_identity import ALL, PACKAGE, build, user

REASON = 'اصلاح ساختگی برای بررسی نسخه جدید'


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityRevisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('revision-author', *ALL)
        cls.editor = user('revision-editor', 'view_identityworkspace', 'add_identityworkspace')
        cls.reviewer = user('revision-reviewer', 'view_identityworkspace', 'review_identityworkspace')
        cls.viewer = user('revision-viewer', 'view_identityworkspace')
        cls.regular = user('revision-nonstaff', *ALL, staff=False)
        cls.parent = build(cls.author)[-1]

    def args(self, **overrides):
        return {'actor': self.editor, 'parent_id': self.parent.pk,
                'data': {**PACKAGE, 'quantity': Decimal('20')}, 'change_reason': REASON,
                'expected_graph_hash': digest(package_snapshot(self.parent)), 'expected_review': 0, **overrides}

    def test_revision_branches_are_distinct_and_reviews_do_not_transfer(self):
        parent_graph = package_snapshot(self.parent)
        review = review_package(actor=self.reviewer, package_id=self.parent.pk, decision='defer', reason=REASON,
                                expected_review=0, expected_graph_hash=digest(parent_graph))
        child = revise_package(**self.args(expected_review=review.pk))
        link = IdentityPackageRevision.objects.select_related('parent__product__formulation',
                                                              'child__product__formulation').get(child=child)
        self.assertTrue(valid_package_revision(link, child.pk))
        self.assertEqual(link.recorded_by_id, self.editor.pk)
        self.assertEqual(child.product_id, self.parent.product_id)
        self.assertEqual(child.quantity, Decimal('20'))
        self.assertEqual(package_snapshot(self.parent), parent_graph)
        self.assertEqual(list(self.parent.reviews.values_list('pk', flat=True)), [review.pk])
        self.assertFalse(child.reviews.exists())
        branch = revise_package(**self.args(data={**PACKAGE, 'quantity': Decimal('30')}, expected_review=review.pk))
        self.assertNotEqual(child.pk, branch.pk)
        self.assertEqual(IdentityPackageRevision.objects.filter(parent=self.parent).count(), 2)
        with self.assertRaises(ValidationError): link.save()
        with self.assertRaises(ValidationError): link.delete()
        editor_with_review = get_user_model().objects.get(pk=self.editor.pk)
        from django.contrib.auth.models import Permission
        editor_with_review.user_permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='review_identityworkspace'))
        with self.assertRaises(PermissionDenied):
            review_package(actor=editor_with_review, package_id=child.pk, decision='defer', reason=REASON,
                           expected_review=0, expected_graph_hash=digest(package_snapshot(child)))
        review_package(actor=self.reviewer, package_id=child.pk, decision='defer', reason=REASON,
                       expected_review=0, expected_graph_hash=digest(package_snapshot(child)))
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_permissions_validation_staleness_and_atomic_rollback(self):
        for actor in [self.viewer, self.regular, self.reviewer]:
            with self.assertRaises(PermissionDenied): revise_package(**self.args(actor=actor))
        for changes in [{'parent_id': 999999}, {'expected_graph_hash': 'f'*64}, {'expected_review': 1},
                        {'change_reason': 'short'}, {'expected_review': True}]:
            with self.assertRaises(IdentityConflict): revise_package(**self.args(**changes))
        with self.assertRaises(IdentityError): revise_package(**self.args(data=PACKAGE))
        with self.assertRaises(IdentityError): revise_package(**self.args(data={**PACKAGE, 'source_url': 'https://example.org/?secret=1'}))
        count = IdentityPackageDraft.objects.count()
        with patch('catalog.identity.IdentityPackageRevision.objects.create', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError): revise_package(**self.args())
        self.assertEqual(IdentityPackageDraft.objects.count(), count)
        self.assertFalse(IdentityPackageRevision.objects.exists())
        review_package(actor=self.reviewer, package_id=self.parent.pk, decision='defer', reason=REASON,
                       expected_review=0, expected_graph_hash=digest(package_snapshot(self.parent)))
        with self.assertRaises(IdentityConflict): revise_package(**self.args())
        self.assertEqual(IdentityPackageDraft.objects.count(), count)

    def test_link_corruption_and_constraint(self):
        child = revise_package(**self.args())
        link = IdentityPackageRevision.objects.get(child=child)
        self.assertTrue(valid_package_revision(link, child.pk))
        IdentityPackageRevision.objects.filter(pk=link.pk).update(change_reason='اطلاعات ناسازگار محرمانه')
        link.refresh_from_db()
        self.assertFalse(valid_package_revision(link, child.pk))
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_detail', args=['package', child.pk]))
        self.assertContains(response, 'پیوند نسخه پیشین ناسازگار')
        self.assertNotContains(response, 'اطلاعات ناسازگار محرمانه')
        response = self.client.get(reverse('staff_identity_detail', args=['package', self.parent.pk]))
        self.assertContains(response, 'پیوند نسخه اصلاحی ناسازگار')
        self.assertNotContains(response, 'اطلاعات ناسازگار محرمانه')
        with self.assertRaises(IntegrityError), transaction.atomic():
            IdentityPackageRevision.objects.filter(pk=link.pk).update(parent=child, child=self.parent)
        with self.assertRaises(IntegrityError), transaction.atomic():
            IdentityPackageRevision.objects.create(parent=self.parent, child=child, recorded_by=self.editor,
                change_reason=REASON, parent_graph_sha256='a'*64, child_graph_sha256='a'*64, payload_sha256='a'*64)
        with self.assertRaises(ProtectedError):
            IdentityPackageDraft.objects.filter(pk=self.parent.pk).delete()
        with self.assertRaises(ProtectedError):
            IdentityPackageDraft.objects.filter(pk=child.pk).delete()

    def test_sequential_revisions_validate_only_immediate_links(self):
        first = revise_package(**self.args())
        first_graph = package_snapshot(first)
        second = revise_package(actor=self.editor, parent_id=first.pk, data={**PACKAGE, 'quantity': Decimal('40')},
                                change_reason=REASON, expected_review=0, expected_graph_hash=digest(first_graph))
        self.assertTrue(valid_package_revision(IdentityPackageRevision.objects.get(child=first), first.pk))
        self.assertTrue(valid_package_revision(IdentityPackageRevision.objects.get(child=second), second.pk))
        first_link = IdentityPackageRevision.objects.get(child=first)
        IdentityPackageRevision.objects.filter(pk=first_link.pk).update(payload_sha256='f'*64)
        self.assertFalse(valid_package_revision(IdentityPackageRevision.objects.get(child=first), first.pk))
        # This intentionally checks the immediate edge, not ancestry authenticity.
        self.assertTrue(valid_package_revision(IdentityPackageRevision.objects.get(child=second), second.pk))

    def test_revision_form_shows_latest_review_and_fails_closed_when_invalid(self):
        graph = package_snapshot(self.parent)
        event = review_package(actor=self.reviewer, package_id=self.parent.pk, decision='defer', reason=REASON,
                               expected_review=0, expected_graph_hash=digest(graph))
        self.client.force_login(self.editor)
        path = reverse('staff_identity_revise', args=[self.parent.pk])
        response = self.client.get(path)
        self.assertContains(response, REASON)
        self.assertEqual(response.context['form'].initial['expected_review'], event.pk)
        IdentityPackageReview.objects.filter(pk=event.pk).update(graph_sha256='f'*64, reason='راز نامعتبر بازبینی ساختگی')
        response = self.client.get(path)
        self.assertContains(response, 'بازبینی ناسازگار است')
        self.assertNotContains(response, 'راز نامعتبر بازبینی ساختگی')
        self.assertNotContains(response, 'name="expected_review"')
        with self.assertRaises(IdentityConflict):
            revise_package(**self.args(expected_review=event.pk))
        payload = {**PACKAGE, 'quantity': '20', 'synthetic_ack': 'on', 'change_reason': REASON,
                   'expected_review': str(event.pk), 'expected_graph_hash': digest(graph)}
        response = self.client.post(path, payload)
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'راز نامعتبر بازبینی ساختگی', status_code=409)
        self.assertFalse(IdentityPackageRevision.objects.exists())

    def test_corrupt_child_suppresses_parent_link_details(self):
        child = revise_package(**self.args())
        IdentityPackageDraft.objects.filter(pk=child.pk).update(description='بسته ناسازگار محرمانه')
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_detail', args=['package', self.parent.pk]))
        self.assertContains(response, 'پیوند نسخه اصلاحی ناسازگار')
        self.assertNotContains(response, REASON)
        self.assertNotContains(response, 'بسته ناسازگار محرمانه')
        self.assertNotContains(response, reverse('staff_identity_detail', args=['package', child.pk]))

    def test_revision_children_keyset_scope_and_escaping(self):
        ids = []
        for i in range(22):
            child = revise_package(**self.args(data={**PACKAGE, 'quantity': Decimal(i + 11)},
                                               change_reason=f'تغییر ساختگی شمارۀ {i:02d} برای آزمون'))
            ids.append(IdentityPackageRevision.objects.get(child=child).pk)
        special = revise_package(**self.args(data={**PACKAGE, 'quantity': Decimal('50')},
                                              change_reason='<script>synthetic test</script>'))
        special_link = IdentityPackageRevision.objects.get(child=special)
        self.client.force_login(self.viewer)
        path = reverse('staff_identity_detail', args=['package', self.parent.pk])
        first = self.client.get(path)
        self.assertEqual([r.pk for r in first.context['child_links']], [special_link.pk, *ids[::-1]][:10])
        self.assertContains(first, '&lt;script&gt;synthetic test&lt;/script&gt;')
        self.assertNotContains(first, '<script>synthetic test</script>')
        next_id = first.context['next_revision_before']
        # A newer revision inserted after page one must not displace older rows.
        revise_package(**self.args(data={**PACKAGE, 'quantity': Decimal('60')}))
        second = self.client.get(path, {'revisions_before': next_id})
        ordered = [special_link.pk, *ids[::-1]]
        self.assertEqual([r.pk for r in second.context['child_links']], ordered[10:20])
        third = self.client.get(path, {'revisions_before': second.context['next_revision_before']})
        self.assertEqual([r.pk for r in third.context['child_links']], ordered[20:])
        self.assertIsNone(third.context['next_revision_before'])
        self.assertContains(third, 'جدیدترین نسخه‌ها')
        for cursor in ('0', '-1', '١', 'x', '9'*20):
            result = self.client.get(path, {'revisions_before': cursor})
            self.assertEqual(result.status_code, 400)
            self.assertIn('no-store', result['Cache-Control'])
        other = build(self.author)[-1]
        other_child = revise_package(**self.args(parent_id=other.pk, expected_graph_hash=digest(package_snapshot(other)),
                                                  change_reason='بسته خصوصی متفاوت برای آزمون'))
        result = self.client.get(path)
        self.assertNotContains(result, reverse('staff_identity_detail', args=['package', other_child.pk]))
        self.assertNotContains(result, 'بسته خصوصی متفاوت برای آزمون')

    def test_stale_graph_and_parent_corruption_fail_closed(self):
        from .models import IngredientDraft
        parent_graph = package_snapshot(self.parent)
        ingredient_id = parent_graph['product']['formulation']['ingredients'][0]['id']
        IngredientDraft.objects.filter(pk=ingredient_id).update(name_fa='متن ناسازگار محرمانه')
        self.client.force_login(self.editor)
        path = reverse('staff_identity_revise', args=[self.parent.pk])
        payload = {**PACKAGE, 'quantity': '20', 'synthetic_ack': 'on', 'change_reason': REASON,
                   'expected_review': '0', 'expected_graph_hash': digest(parent_graph)}
        response = self.client.post(path, payload)
        self.assertContains(response, 'بسته یا وابستگی آن ناسازگار است')
        self.assertNotContains(response, 'متن ناسازگار محرمانه')
        self.assertFalse(IdentityPackageRevision.objects.exists())

    def test_web_workflow_privacy_csrf_and_conflict(self):
        path = reverse('staff_identity_revise', args=[self.parent.pk])
        self.assertEqual(self.client.get(path).status_code, 302)
        self.client.force_login(self.viewer); self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.regular); self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.editor)
        response = self.client.get(path)
        self.assertContains(response, 'نسخه اصلاحی بسته ساختگی')
        self.assertNotContains(response, 'name="product_id"')
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        payload = {**PACKAGE, 'quantity': '20', 'synthetic_ack': 'on', 'change_reason': REASON,
                   'expected_review': 0, 'expected_graph_hash': digest(package_snapshot(self.parent))}
        csrf_client = Client(enforce_csrf_checks=True); csrf_client.force_login(self.editor)
        self.assertEqual(csrf_client.post(path, payload).status_code, 403)
        with override_settings(STAFF_PORTAL_ENABLED=False): self.assertEqual(self.client.get(path).status_code, 404)
        response = self.client.post(path, {**payload, 'synthetic_ack': ''})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(IdentityPackageRevision.objects.count(), 0)
        response = self.client.post(path, {**payload, 'product_id': 999999})
        self.assertEqual(response.status_code, 302)
        child = IdentityPackageRevision.objects.get().child
        self.assertEqual(child.product_id, self.parent.product_id)
        self.assertRedirects(response, reverse('staff_identity_detail', args=['package', child.pk]))
        self.assertContains(self.client.get(response.url), f'بسته {self.parent.pk}')
        self.assertContains(self.client.get(reverse('staff_identity_detail', args=['package', self.parent.pk])), f'بسته {child.pk}')
        review_package(actor=self.reviewer, package_id=self.parent.pk, decision='defer', reason=REASON,
                       expected_review=0, expected_graph_hash=digest(package_snapshot(self.parent)))
        response = self.client.post(path, payload)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'صفحه را دوباره بارگذاری کنید', status_code=409)
        self.assertNotContains(response, 'name="expected_review"', status_code=409)
        self.assertEqual(IdentityPackageRevision.objects.count(), 1)
        self.assertNotContains(self.client.get('/'), REASON)


class ConcurrentRevisionTests(TransactionTestCase):
    def setUp(self):
        self.author = user('revision-race-author', *ALL)
        self.actors = [user(f'revision-race-{i}', *ALL) for i in range(2)]
        self.parent = build(self.author)[-1]
        self.graph_hash = digest(package_snapshot(self.parent))

    def race(self, operations):
        barrier = Barrier(2, timeout=10)
        def worker(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actors[index].pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait()
                try:
                    operations[index](actor)
                    return 'created'
                except IdentityConflict:
                    return 'conflict'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, range(2)))

    def revise(self, actor, quantity):
        return revise_package(actor=actor, parent_id=self.parent.pk, data={**PACKAGE, 'quantity': Decimal(quantity)},
                              change_reason=REASON, expected_graph_hash=self.graph_hash, expected_review=0)

    def test_parallel_revisions_form_two_atomic_branches(self):
        result = self.race([lambda actor: self.revise(actor, '20'), lambda actor: self.revise(actor, '30')])
        self.assertEqual(result, ['created', 'created'])
        links = IdentityPackageRevision.objects.select_related('parent__product__formulation',
                                                               'child__product__formulation').all()
        self.assertEqual(links.count(), 2)
        self.assertEqual(IdentityPackageDraft.objects.count(), 3)
        for link in links: self.assertTrue(valid_package_revision(link, link.child_id))
        self.assertFalse(self.parent.reviews.exists())

    def test_review_vs_revision_uses_shared_parent_lock(self):
        def review(actor):
            review_package(actor=actor, package_id=self.parent.pk, decision='defer', reason=REASON,
                           expected_review=0, expected_graph_hash=self.graph_hash)
        revision, review_result = self.race([lambda actor: self.revise(actor, '20'), review])
        self.assertEqual(review_result, 'created')
        self.assertEqual(self.parent.reviews.count(), 1)
        self.assertIn(revision, ('created', 'conflict'))
        self.assertEqual(IdentityPackageRevision.objects.count(), int(revision == 'created'))
        self.assertEqual(IdentityPackageDraft.objects.count(), 1 + int(revision == 'created'))
