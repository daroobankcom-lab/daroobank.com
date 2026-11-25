"""Public search rechecks synthetic current fields after stale projection matches."""
from datetime import datetime, timezone

from django.test import TestCase
from django.urls import reverse

from .models import ProductPresentation
from .services import MAX_SEARCH_CANDIDATES


class SearchProjectionGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='نام ساختگی قدیمی', name_en='Oldsynthetic', manufacturer='سازنده فرضی',
            strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001234',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
        )

    def test_stale_positive_is_filtered_without_claiming_false_negatives_are_fixed(self):
        # Bypass save() to simulate an out-of-band write and stale search_text.
        ProductPresentation.objects.filter(pk=self.product.pk).update(name_en='Newsynthetic')
        api_url, html_url = reverse('search_api'), reverse('search')
        with self.assertNumQueries(1):
            old = self.client.get(api_url, {'q': 'oldsynthetic'})
        self.assertEqual(old.status_code, 200)
        self.assertEqual(old.json()['data'], [])
        self.assertEqual(old['Cache-Control'], 'no-store')
        self.assertEqual(old['Referrer-Policy'], 'no-referrer')
        html = self.client.get(html_url, {'q': 'oldsynthetic'})
        self.assertNotContains(html, f'/products/{self.product.pk}/')
        # No SQL candidate exists for the new term until the projection is fixed.
        self.assertEqual(self.client.get(api_url, {'q': 'newsynthetic'}).json()['data'], [])
        self.assertEqual(self.client.get(reverse('presentation_api', args=[self.product.pk])).status_code, 200)
        # Normal model save updates projections; both terms then behave correctly.
        self.product.refresh_from_db()
        self.product.save(update_fields=['name_en'])
        self.assertEqual(self.client.get(api_url, {'q': 'oldsynthetic'}).json()['data'], [])
        self.assertEqual([row['id'] for row in self.client.get(api_url, {'q': 'newsynthetic'}).json()['data']],
                         [self.product.pk])

    def test_stale_projection_does_not_block_a_current_match_and_persian_normalization(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(name_en='Newsynthetic')
        # The index is stale but this query still matches an unchanged current field.
        data = self.client.get(reverse('search_api'), {'q': '۰۰۱۲۳۴'}).json()['data']
        self.assertEqual([row['id'] for row in data], [self.product.pk])
        self.assertEqual(data[0]['name_en'], 'Newsynthetic')
        self.assertContains(self.client.get(reverse('search'), {'q': 'ميلي گرم'}), 'نام ساختگی قدیمی')

    def test_empty_bounded_page_of_stale_hits_can_continue(self):
        rows = [ProductPresentation(
            name_fa=f'A synthetic {i:03}', name_en='', manufacturer='Synthetic maker',
            strength='1 mg', dosage_form='tablet', package_description='10', irc='',
            source_name='Synthetic source', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
            search_text='syntheticneedle stale projection', irc_normalized='',
        ) for i in range(MAX_SEARCH_CANDIDATES)]
        ProductPresentation.objects.bulk_create(rows)
        valid = ProductPresentation.objects.create(
            name_fa='Z syntheticneedle', manufacturer='Synthetic maker', strength='1 mg',
            dosage_form='tablet', package_description='10', source_name='Synthetic source',
            source_url='https://example.org/synthetic', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            published=True,
        )
        response = self.client.get(reverse('search_api'), {'q': 'syntheticneedle'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data'], [])
        cursor = response.json()['meta']['next_cursor']
        self.assertIsNotNone(cursor)
        self.assertNotIn('A synthetic', cursor)
        html = self.client.get(reverse('search'), {'q': 'syntheticneedle'})
        self.assertContains(html, 'می‌توانید بخش بعدی را بررسی کنید')
        self.assertNotContains(html, 'A synthetic')
        page2 = self.client.get(reverse('search_api'), {'q': 'syntheticneedle', 'cursor': cursor}).json()
        self.assertEqual([item['id'] for item in page2['data']], [valid.pk])
        self.assertIsNone(page2['meta']['next_cursor'])
