"""Local digit support for private scan positions; no database access."""
import random
from django.test import SimpleTestCase

from catalog.quality import MAX_PK as QUALITY_MAX
from sources.date_inspection import MAX_PK as DATE_MAX
from .scan_input import parse_scan_after


class ScanInputTests(SimpleTestCase):
    def test_ascii_persian_arabic_indic_and_mixed_digits(self):
        self.assertEqual(QUALITY_MAX, DATE_MAX)
        cases = {'0': 0, '۰۰۰': 0, '١٢٣': 123, '۱2٣۴': 1234,
                 '۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۷': QUALITY_MAX,
                 '٩٢٢٣٣٧٢٠٣٦٨٥٤٧٧٥٨٠٧': QUALITY_MAX}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_scan_after(raw, maximum=QUALITY_MAX), expected)

    def test_invalid_format_and_above_limit_rejected(self):
        for raw in [None, 0, '', ' ۱', '۱ ', '+۱', '-١', '۱e2', '1.0', '1,000', '۱\u200c۲',
                    '１２３', '१२३', '۱\x00', '۱\ud800', '۰' * 20,
                    '۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۸', '٩٢٢٣٣٧٢٠٣٦٨٥٤٧٧٥٨٠٨']:
            with self.subTest(raw=ascii(raw)), self.assertRaises(ValueError):
                parse_scan_after(raw, maximum=QUALITY_MAX)

    def test_seeded_mixed_script_round_trips_without_float(self):
        rng = random.Random(20261122)
        scripts = ['0123456789', '۰۱۲۳۴۵۶۷۸۹', '٠١٢٣٤٥٦٧٨٩']
        for _ in range(500):
            value = rng.randrange(QUALITY_MAX + 1)
            raw = ''.join(rng.choice(scripts)[int(digit)] for digit in str(value))
            self.assertEqual(parse_scan_after(raw, maximum=QUALITY_MAX), value)
