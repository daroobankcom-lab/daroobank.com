"""Independent integer oracle for bounded synthetic price conversion examples."""
import random

from django.test import SimpleTestCase

from .importer import ImportValidationError, MAX_RIAL, amount_to_rial


class PriceAmountOracleTests(SimpleTestCase):
    def test_seeded_decimal_inputs_against_integer_arithmetic(self):
        rng = random.Random(6122026)
        digit_sets = ('0123456789', '۰۱۲۳۴۵۶۷۸۹', '٠١٢٣٤٥٦٧٨٩')
        counts = {'accepted': 0, 'rejected': 0}
        for case in range(5000):
            integer = ''.join(str(rng.randrange(10)) for _ in range(rng.randrange(1, 35)))
            fraction = ''.join(str(rng.randrange(10)) for _ in range(rng.randrange(0, 15)))
            value = integer + ('.' + fraction if fraction else '')
            value = value.translate(str.maketrans(digit_sets[0], rng.choice(digit_sets)))
            if fraction and rng.randrange(2):
                value = value.replace('.', '٫')
            currency = rng.choice(('TOMAN', 'RIAL'))
            numerator = int(integer + fraction) * (10 if currency == 'TOMAN' else 1)
            divisor = 10 ** len(fraction)
            quotient, remainder = divmod(numerator, divisor)
            expected = quotient if remainder == 0 and 0 < quotient <= MAX_RIAL else None
            try:
                actual = amount_to_rial(value, currency)
            except ImportValidationError:
                actual = None
            self.assertEqual(actual, expected, f'synthetic seeded case {case}')
            counts['accepted' if actual is not None else 'rejected'] += 1
        self.assertGreater(counts['accepted'], 200)
        self.assertGreater(counts['rejected'], 4000)

    def test_selected_integer_boundaries(self):
        for value, currency, expected in ((str(MAX_RIAL), 'RIAL', MAX_RIAL),
                                          (str(MAX_RIAL + 1), 'RIAL', None),
                                          ('0', 'RIAL', None), ('0.1', 'TOMAN', 1),
                                          ('0.01', 'TOMAN', None), ('1.0000', 'RIAL', 1)):
            with self.subTest(value=value, currency=currency):
                if expected is None:
                    with self.assertRaises(ImportValidationError):
                        amount_to_rial(value, currency)
                else:
                    self.assertEqual(amount_to_rial(value, currency), expected)
