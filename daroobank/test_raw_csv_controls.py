"""Synthetic coverage for raw controls in every product and price CSV column."""
import csv
import io

from django.test import SimpleTestCase

from catalog.intake import FIELDS as PRODUCT_FIELDS, IntakeError, parse_product_csv
from pricing.importer import FIELDS as PRICE_FIELDS, ImportValidationError, parse_csv


def encode_row(fields, row):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerow(row)
    return io.BytesIO(stream.getvalue().encode('utf-8'))


class RawCsvControlTests(SimpleTestCase):
    def test_every_column_rejects_selected_controls_at_both_edges(self):
        product = dict(source_record_id='record', name_fa='نام ساختگی', name_en='Synthetic',
                       manufacturer='سازنده', strength='5 mg', dosage_form='قرص',
                       package_description='10 عدد', irc='123')
        price = dict(source_record_id='record', irc='123', manufacturer='سازنده', strength='5 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='123', currency='RIAL',
                     category='retail', unit='package', effective_date='2026-01-02', source_published_date='')
        for fields, row, parser, error in ((PRODUCT_FIELDS, product, parse_product_csv, IntakeError),
                                           (PRICE_FIELDS, price, parse_csv, ImportValidationError)):
            for field in fields:
                for char in ('\x00', '\t', '\n', '\r', '\x7f', '\u0085'):
                    for prepend in (False, True):
                        with self.subTest(parser=parser.__name__, field=field, codepoint=ord(char), prepend=prepend):
                            value = char + row[field] if prepend else row[field] + char
                            with self.assertRaises(error) as raised:
                                parser(encode_row(fields, {**row, field: value}))
                            self.assertNotIn(value, str(raised.exception))

    def test_selected_ordinary_spaces_and_persian_joiner_remain_supported(self):
        product = dict(source_record_id=' record ', name_fa=' نام\u200cساختگی ', name_en='',
                       manufacturer='سازنده', strength='5 mg', dosage_form='قرص',
                       package_description='10 عدد', irc='123')
        price = dict(source_record_id=' record ', irc='123', manufacturer=' شرکت\u200cساختگی ', strength='5 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='123', currency='RIAL',
                     category='retail', unit='package', effective_date='', source_published_date='')
        parsed_product = parse_product_csv(encode_row(PRODUCT_FIELDS, product))[0]
        parsed_price = parse_csv(encode_row(PRICE_FIELDS, price))[0][0]
        self.assertEqual(parsed_product['source_record_id'], 'record')
        self.assertEqual(parsed_product['name_fa'], 'نام\u200cساختگی')
        self.assertEqual(parsed_price['source_record_id'], 'record')
        self.assertEqual(parsed_price['manufacturer'], 'شرکت\u200cساختگی')
