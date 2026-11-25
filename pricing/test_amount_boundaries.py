"""Length and precision boundaries for direct synthetic amount conversion."""
import random
import unicodedata
from decimal import localcontext

from django.test import SimpleTestCase

from catalog.normalization import normalize_search
from .importer import ImportValidationError, MAX_RIAL, amount_to_rial


class PriceAmountBoundaryTests(SimpleTestCase):
    def test_helper_rejects_oversized_input_before_decimal_rounding(self):
        # Decimal context rounding at 80 significant digits otherwise converts
        # this nonintegral value to 1, contrary to the no-rounding contract.
        with self.assertRaises(ImportValidationError):
            amount_to_rial('1.' + '0' * 80 + '1', 'RIAL')
        with self.assertRaises(ImportValidationError):
            amount_to_rial('0.' + '0' * 80 + '1', 'TOMAN')

    def test_non_string_amount_is_rejected_without_type_error(self):
        for value in (None, 1, True, b'1'):
            with self.subTest(value=value), self.assertRaises(ImportValidationError):
                amount_to_rial(value, 'RIAL')

    def test_amount_does_not_silently_remove_controls_or_combining_marks(self):
        unsafe = ('1\u200b2', '1\u202e2', '1\u0301', '1\u20dd', '1\ufe0f', '\t1', '\n1',
                  '\u200f1', '1\u2028', '\u00a81')  # NFKC of the last adds a combining mark.
        for value in unsafe:
            for currency in ('RIAL', 'TOMAN'):
                with self.subTest(value=repr(value), currency=currency), self.assertRaises(ImportValidationError):
                    amount_to_rial(value, currency)
        self.assertEqual(amount_to_rial(' ۱۲۳ ', 'RIAL'), 123)
        self.assertEqual(amount_to_rial('⑩.0', 'RIAL'), 10)

    def test_all_unicode_codepoints_with_unsafe_categories_are_rejected_in_an_amount(self):
        forbidden = {'Cc', 'Cs', 'Cf', 'Mn', 'Me', 'Zl', 'Zp'}
        checked = 0
        for codepoint in range(0x110000):
            char = chr(codepoint)
            if (unicodedata.category(char) in forbidden
                    or any(unicodedata.category(c) in forbidden for c in unicodedata.normalize('NFKC', char))):
                checked += 1
                try:
                    amount_to_rial('1' + char + '2', 'RIAL')
                except ImportValidationError:
                    continue
                self.fail(f'Forbidden synthetic codepoint U+{codepoint:04X} was accepted')
        self.assertGreater(checked, 3000)

    def test_conversion_does_not_depend_on_ambient_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            context.Emax = 2
            context.Emin = -2
            self.assertEqual(amount_to_rial('1000', 'RIAL'), 1000)
            self.assertEqual(amount_to_rial('0.1', 'TOMAN'), 1)
            with self.assertRaises(ImportValidationError):
                amount_to_rial('0.0001', 'TOMAN')

    def test_non_string_currency_is_rejected_without_type_error(self):
        for value in (None, 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ImportValidationError):
                amount_to_rial('1', value)

    def test_toman_upper_boundary_fraction_and_leading_zeroes(self):
        self.assertEqual(amount_to_rial('000922337203685477580.7000', 'TOMAN'), MAX_RIAL)
        for amount in ('922337203685477580.8', '922337203685477580.70001',
                       '922337203685477581', '000.000'):
            with self.subTest(amount=amount), self.assertRaises(ImportValidationError):
                amount_to_rial(amount, 'TOMAN')
        self.assertEqual(amount_to_rial('000.10000', 'TOMAN'), 1)

    def test_all_two_decimal_amounts_below_one_hundred_against_integer_arithmetic(self):
        for integer in range(100):
            for fraction in range(100):
                text = f'{integer:02}.{fraction:02}'
                for currency, factor in (('RIAL', 1), ('TOMAN', 10)):
                    quotient, remainder = divmod((100 * integer + fraction) * factor, 100)
                    expected = quotient if not remainder and quotient else None
                    try:
                        actual = amount_to_rial(text, currency)
                    except ImportValidationError:
                        actual = None
                    self.assertEqual(actual, expected, f'synthetic {text} {currency}')

    def test_expanded_unicode_amounts_against_integer_arithmetic(self):
        rng = random.Random(24011226)
        chars = '0123456789۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩⑩⑪⑳㉚㊿'
        for case in range(3000):
            integer = ''.join(rng.choice(chars) for _ in range(rng.randrange(1, 20)))
            fractional = ''.join(rng.choice(chars) for _ in range(rng.randrange(0, 30)))
            value = integer + ('.' + fractional if fractional else '')
            currency = rng.choice(('RIAL', 'TOMAN'))
            normalized = normalize_search(value)
            left, _, right = normalized.partition('.')
            numerator = int(left + right) * (10 if currency == 'TOMAN' else 1)
            quotient, remainder = divmod(numerator, 10 ** len(right))
            expected = quotient if not remainder and 0 < quotient <= MAX_RIAL else None
            try:
                actual = amount_to_rial(value, currency)
            except ImportValidationError:
                actual = None
            self.assertEqual(actual, expected, f'synthetic expanded case {case}')

    def test_fifty_character_boundary_and_normalization_expansion(self):
        self.assertEqual(amount_to_rial('1.' + '0' * 48, 'RIAL'), 1)
        # 50 input characters expand to 98 normalized characters; it must not
        # become a whole-rial value through decimal rounding.
        with self.assertRaises(ImportValidationError):
            amount_to_rial('1.' + '⑩' * 48, 'RIAL')
        with self.assertRaises(ImportValidationError):
            amount_to_rial('1.' + '0' * 49, 'RIAL')
