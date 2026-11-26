"""Identifier-shape parity on staff object routes; synthetic evidence, not a review.

ADR 0204 compares the denial for an existing row with the denial for one missing
primary key. A route can still leak through the *shape* of an identifier: a
different answer for zero, for an out-of-range value, for a non-numeric segment or
for a wrong HTTP method tells a probing client something about the row or about the
view's internals even when the status code stays a denial.

This suite probes all 23 object routes with eight identifier variants and both
method directions, and pins what each account shape receives:

* an unauthorized shape gets one identical 403 for every variant, including the
  existing row;
* an authorized shape gets one identical 404 for every invalid variant, so absence
  and out-of-range are indistinguishable;
* a method mismatch is answered before authorization, identically for every shape.

It records current behavior on a development-only portal with synthetic data. It is
not an authorization review, and timing is not compared here either.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS, satisfies
from .test_staff_authorization_objects import COUNTED_MODELS, OBJECT_ROUTES, build_object_rows
from .test_staff_denial_parity import VOLATILE_HEADERS, comparable

PLACEHOLDER = 999_999_999
# Identifiers the ``<int:pk>`` converter accepts, so the route resolves.
RESOLVING = ('999999999', '0', '99999999999999999999', '9223372036854775807')
# Identifiers the converter rejects, so no route matches at all. These cannot be
# produced by ``reverse`` and are built by substituting into a resolved URL.
NON_MATCHING = ('-1', 'abc', '1.5', '1%2f..', '', ' 1', '1 ', '+1', '١')
ALL_INVALID = RESOLVING + NON_MATCHING
# Object routes declared with `require_http_methods(['GET', 'POST'])`: the method is
# not a gate, because the same view renders the form and accepts its submission.
DUAL_METHOD_ROUTES = frozenset({'staff_clinical_revise', 'staff_clinical_reference_create',
                                'staff_identity_revise', 'staff_identity_revise_component'})


def comparable_of(response):
    return comparable(response)


def header_dict(response):
    """The same header view as `comparable`, but as a dict for single assertions."""
    return headers_without_volatile(response)


def headers_without_volatile(response):
    return {key.lower(): value for key, value in response.items() if key.lower() not in VOLATILE_HEADERS}


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffIdentifierParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('identifier-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('identifier-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('identifier-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('identifier-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('identifier-author', password='synthetic-only', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.rows = build_object_rows(author)

    def object_routes(self):
        return [(name, method, requirement) for name, _kwargs, method, requirement in ROUTES
                if name in OBJECT_ROUTES]

    def existing_kwargs(self, name):
        rows = self.rows
        table = {
            'staff_source_detail': (rows.claim.pk, {}), 'staff_source_review_inspection': (rows.claim.pk, {}),
            'staff_source_review': (rows.claim.pk, {}), 'staff_product_detail': (rows.candidate.pk, {}),
            'staff_product_review_inspection': (rows.candidate.pk, {}), 'staff_product_review': (rows.candidate.pk, {}),
            'staff_price_detail': (rows.price.pk, {}), 'staff_price_review_inspection': (rows.price.pk, {}),
            'staff_price_review': (rows.price.pk, {}), 'staff_clinical_detail': (rows.draft.pk, {}),
            'staff_clinical_review_inspection': (rows.draft.pk, {}), 'staff_clinical_lineage': (rows.draft.pk, {}),
            'staff_clinical_revise': (rows.draft.pk, {}), 'staff_clinical_reference_create': (rows.draft.pk, {}),
            'staff_clinical_review': (rows.draft.pk, {}),
            'staff_identity_detail': (rows.package.pk, {'kind': 'package'}),
            'staff_identity_lineage': (rows.package.pk, {'kind': 'package'}),
            'staff_identity_revise_component': (rows.ingredient.pk, {'kind': 'ingredient'}),
            'staff_identity_revise': (rows.package.pk, {}), 'staff_identity_review': (rows.package.pk, {}),
            'staff_catalog_quality_irc': (rows.presentation.pk, {}),
            'staff_import_receipt_detail': (rows.receipt.pk, {}),
            'staff_import_manifest_inspection': (rows.receipt.pk, {}),
        }
        return table[name]

    def url_for(self, name, identifier):
        """Resolve the route with a placeholder key, then substitute the identifier."""
        pk, extra = self.existing_kwargs(name)
        base = reverse(name, kwargs=dict(extra, pk=PLACEHOLDER))
        return base.replace(str(PLACEHOLDER), identifier, 1), pk, extra

    def request(self, account, url, method):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        return client.get(url) if method == 'GET' else client.post(url, {})

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_the_variant_lists_are_what_the_pins_describe(self):
        self.assertEqual(len(OBJECT_ROUTES), 23)
        self.assertEqual(len(self.object_routes()), 23)
        self.assertEqual(len(RESOLVING), 4)
        self.assertEqual(len(NON_MATCHING), 9)
        self.assertEqual(len(ALL_INVALID), 13)
        for name, _method, _requirement in self.object_routes():
            with self.subTest(route=name):
                url, _pk, _extra = self.url_for(name, str(PLACEHOLDER))
                self.assertIn(str(PLACEHOLDER), url)

    def url_for_identifier(self, name, identifier):
        pk, extra = self.existing_kwargs(name)
        if identifier in RESOLVING or identifier == str(pk):
            return reverse(name, kwargs=dict(extra, pk=identifier))
        return self.url_for(name, identifier)[0]

    def test_identifiers_the_converter_accepts_give_one_identical_answer_per_shape(self):
        # Group A: the `<int:pk>` converter accepts these, so the view runs. An
        # unauthorized shape must get the same 403 for the existing row, for zero,
        # for a missing key, for a 20-digit key and for the largest signed 64-bit
        # key; an authorized shape must get the same 404 for all four invalid ones,
        # so absence is indistinguishable from out-of-range.
        for account in (self.outsider, self.bare, self.viewer, self.full):
            for name, method, requirement in self.object_routes():
                pk, _extra = self.existing_kwargs(name)
                authorized = satisfies(account, requirement)
                variants = ([str(pk)] + list(RESOLVING)) if not authorized else list(RESOLVING)
                seen = {identifier: comparable_of(self.request(
                    account, self.url_for_identifier(name, identifier), method)) for identifier in variants}
                with self.subTest(account=account.username, route=name):
                    self.assertEqual(len(set(seen.values())), 1,
                                     f'The answer differs by identifier shape: {sorted(seen)}')
                    self.assertEqual(next(iter(seen.values()))[0], 404 if authorized else 403)

    def test_identifiers_the_converter_rejects_never_reach_the_view(self):
        # Group B: no route matches, so every shape - including an unauthorized or
        # anonymous one - gets the identical unmatched-URL 404 rather than a 403.
        # Recorded as a finding: a malformed identifier is answered differently from
        # a well-formed but forbidden one, which reveals URL grammar but says nothing
        # about whether a row exists, and the answer is the same for every account.
        shapes = (None, self.outsider, self.bare, self.viewer, self.full)
        for name, method, _requirement in self.object_routes():
            per_identifier = {}
            for identifier in NON_MATCHING:
                url = self.url_for(name, identifier)[0]
                per_identifier[identifier] = {comparable_of(self.request(account, url, method))
                                              for account in shapes}
            with self.subTest(route=name):
                self.assertEqual({len(group) for group in per_identifier.values()}, {1},
                                 'A rejected identifier is answered differently per account shape.')
                flat = {next(iter(group)) for group in per_identifier.values()}
                self.assertEqual(len(flat), 1, 'Rejected identifiers are answered differently from each other.')
                status, body, headers = next(iter(flat))
                self.assertEqual(status, 404)
                self.assertEqual(body.count(b'Not Found'), 2)
                self.assertNotIn(b'MARKER', body)
                header_map = dict(headers)
                self.assertIn('no-store', header_map['cache-control'])
                self.assertEqual(header_map['x-robots-tag'], 'noindex, nofollow')
                self.assertEqual(header_map['referrer-policy'], 'same-origin')

    def test_method_mismatches_are_answered_identically_for_authenticated_accounts(self):
        # The route table records the method the matrix probes with, not the set of
        # allowed methods. Three groups exist among the 23 object routes:
        #
        #   safe-only (14)  - an unsafe method is rejected with 405 *before*
        #                     authorization, identically for every authenticated
        #                     account, with an empty body and an Allow header;
        #   POST-only (5)   - a GET is rejected the same way, again before
        #                     authorization, so the method answer reveals nothing
        #                     about the account or the row;
        #   GET+POST (4)    - the method is not a gate at all: an unauthorized
        #                     account gets the usual 403 and an authorized one gets
        #                     the form re-rendered for its empty POST.
        #
        # An anonymous request is redirected to the login in every group.
        login = reverse('staff_login')
        for name, method, requirement in self.object_routes():
            wrong = 'POST' if method == 'GET' else 'GET'
            pk, extra = self.existing_kwargs(name)
            url = reverse(name, kwargs=dict(extra, pk=pk))
            responses = {account.username: comparable_of(self.request(account, url, wrong))
                         for account in (self.outsider, self.bare, self.viewer, self.full)}
            group = ('dual' if name in DUAL_METHOD_ROUTES else
                     'post-only' if method == 'POST' else 'safe-only')
            with self.subTest(route=name, wrong_method=wrong, group=group):
                if group == 'dual':
                    denied = [comparable_of(self.request(account, url, wrong))
                              for account in (self.outsider, self.bare, self.viewer)
                              if not satisfies(account, requirement)]
                    self.assertGreaterEqual(len(denied), 2)
                    self.assertEqual(len(set(denied)), 1, 'Unauthorized accounts are answered differently.')
                    self.assertEqual(denied[0][0], 403)
                    authorized = comparable_of(self.request(self.full, url, wrong))
                    self.assertIn(authorized[0], (200, 400, 409),
                                  'A dual-method route must not reject the method for an authorized account.')
                else:
                    self.assertEqual(len(set(responses.values())), 1,
                                     'The method answer differs between authenticated accounts.')
                    status, body, headers = responses[self.outsider.username]
                    self.assertEqual(status, 405)
                    self.assertEqual(body, b'')
                    header_map = dict(headers)
                    self.assertEqual(header_map['allow'], method + ', HEAD' if method == 'GET' else 'POST')
                    self.assertIn('no-store', header_map['cache-control'])
                    self.assertEqual(header_map['x-robots-tag'], 'noindex, nofollow')
                anonymous = self.request(None, url, wrong)
                self.assertEqual(anonymous.status_code, 302)
                self.assertTrue(anonymous['Location'].startswith(login))

    def test_the_three_method_groups_are_the_sizes_recorded_here(self):
        groups = {'dual': [], 'post-only': [], 'safe-only': []}
        for name, method, _requirement in self.object_routes():
            groups['dual' if name in DUAL_METHOD_ROUTES else 'post-only' if method == 'POST'
                   else 'safe-only'].append(name)
        self.assertEqual(len(groups['dual']), 4)
        self.assertEqual(len(groups['post-only']), 5)
        self.assertEqual(len(groups['safe-only']), 14)
        self.assertEqual(set(groups['dual']), set(DUAL_METHOD_ROUTES))

    def test_probing_every_identifier_and_method_variant_writes_nothing(self):
        # Includes the wrong-method POSTs against existing rows, which is where an
        # accidental write would show up on the four dual-method form routes.
        before = self.counts()
        for account in (None, self.outsider, self.bare, self.viewer, self.full):
            for name, method, _requirement in self.object_routes():
                pk, extra = self.existing_kwargs(name)
                for identifier in ALL_INVALID:
                    url = (reverse(name, kwargs=dict(extra, pk=identifier))
                           if identifier in RESOLVING else self.url_for(name, identifier)[0])
                    self.request(account, url, method)
                self.request(account, reverse(name, kwargs=dict(extra, pk=pk)),
                             'POST' if method == 'GET' else 'GET')
        self.assertEqual(self.counts(), before)
