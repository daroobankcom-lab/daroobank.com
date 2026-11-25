"""Recovery from invalid hidden review tokens, using synthetic records only."""
from django.test import TestCase, override_settings
from django.urls import reverse

from . import test_candidate_review_error_summary as candidate_fixtures
from . import test_review_error_summaries as other_fixtures


@override_settings(STAFF_PORTAL_ENABLED=True)
class CandidateHiddenRetryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        candidate_fixtures.CandidateReviewErrorSummaryTests.setUpTestData.__func__(cls)

    def test_each_invalid_hidden_field_offers_get_restart_without_writes(self):
        self.client.force_login(self.reviewer)
        for detail, review, candidate, model, data in candidate_fixtures.CandidateReviewErrorSummaryTests.cases(self):
            for field in (key for key in data if key.startswith('expected_')):
                with self.subTest(domain=detail, field=field):
                    response = self.client.post(reverse(review, args=[candidate.pk]), {**data, field: 'bad-hidden-token'})
                    self.assertEqual(response.status_code, 400)
                    self.assertContains(response, 'اطلاعات پنهان بازبینی معتبر نیست', status_code=400)
                    url = reverse(detail, args=[candidate.pk])
                    self.assertContains(response, f'href="{url}">بازگشت به جزئیات و شروع دوباره', status_code=400)
                    self.assertEqual(model.objects.count(), 0)
                    self.assertEqual(self.client.get(url).status_code, 200)
                    self.assertIn('no-store', response['Cache-Control'])

    def test_visible_only_error_does_not_offer_restart(self):
        self.client.force_login(self.reviewer)
        for _, review, candidate, _, data in candidate_fixtures.CandidateReviewErrorSummaryTests.cases(self):
            response = self.client.post(reverse(review, args=[candidate.pk]), {**data, 'reason': 'short'})
            self.assertNotContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400)

    def test_multiple_hidden_errors_offer_one_link_and_unavailable_form_offers_none(self):
        for _, review, candidate, model, data in candidate_fixtures.CandidateReviewErrorSummaryTests.cases(self):
            invalid = {**data, **{key: 'hidden-canary' for key in data if key.startswith('expected_')}}
            self.client.force_login(self.reviewer)
            response = self.client.post(reverse(review, args=[candidate.pk]), invalid)
            self.assertContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400, count=1)
            self.client.force_login(self.stager)
            response = self.client.post(reverse(review, args=[candidate.pk]), invalid)
            self.assertNotContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400)
            self.assertNotContains(response, 'hidden-canary', status_code=400)
            self.assertEqual(model.objects.count(), 0)


@override_settings(STAFF_PORTAL_ENABLED=True)
class OtherHiddenRetryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        other_fixtures.OtherReviewErrorSummaryTests.setUpTestData.__func__(cls)

    def test_each_invalid_hidden_field_offers_get_restart_without_writes(self):
        self.client.force_login(self.reviewer)
        for detail, detail_args, review, review_args, model, data in other_fixtures.OtherReviewErrorSummaryTests.cases(self):
            for field in (key for key in data if key.startswith('expected_')):
                with self.subTest(domain=detail, field=field):
                    response = self.client.post(reverse(review, args=review_args), {**data, field: 'bad-hidden-token'})
                    self.assertEqual(response.status_code, 400)
                    self.assertContains(response, 'اطلاعات پنهان بازبینی معتبر نیست', status_code=400)
                    url = reverse(detail, args=detail_args)
                    self.assertContains(response, f'href="{url}">بازگشت به جزئیات و شروع دوباره', status_code=400)
                    self.assertEqual(model.objects.count(), 0)
                    self.assertEqual(self.client.get(url).status_code, 200)
                    self.assertIn('no-store', response['Cache-Control'])

    def test_visible_only_error_does_not_offer_restart(self):
        self.client.force_login(self.reviewer)
        for _, _, review, review_args, _, data in other_fixtures.OtherReviewErrorSummaryTests.cases(self):
            response = self.client.post(reverse(review, args=review_args), {**data, 'reason': 'short'})
            self.assertNotContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400)

    def test_multiple_hidden_errors_offer_one_link_and_unavailable_form_offers_none(self):
        for _, _, review, review_args, model, data in other_fixtures.OtherReviewErrorSummaryTests.cases(self):
            invalid = {**data, **{key: 'hidden-canary' for key in data if key.startswith('expected_')}}
            self.client.force_login(self.reviewer)
            response = self.client.post(reverse(review, args=review_args), invalid)
            self.assertContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400, count=1)
            self.client.force_login(self.author)
            response = self.client.post(reverse(review, args=review_args), invalid)
            self.assertNotContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400)
            self.assertNotContains(response, 'hidden-canary', status_code=400)
            self.assertEqual(model.objects.count(), 0)
