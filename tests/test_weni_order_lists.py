import unittest

from pedido_utils import (
    normalize_farmalider_payment_code,
    parse_weni_order_list,
    serialize_weni_order_list,
)


class WeniOrderListTests(unittest.TestCase):
    def test_round_trip_preserves_decimal_commas_quotes_and_multiline_names(self):
        names = ['Produto 0,5 MG', 'Nome "especial"', 'Nome\ncom continuação', 'Nome\rcom continuação']
        self.assertEqual(parse_weni_order_list(serialize_weni_order_list(names)), names)

    def test_ordinary_lists_remain_compatible(self):
        self.assertEqual(serialize_weni_order_list(["Produto A", "Produto B"]), "Produto A, Produto B")
        self.assertEqual(parse_weni_order_list("Produto A, Produto B"), ["Produto A", "Produto B"])
        self.assertEqual(parse_weni_order_list('"Produto 0,5 MG", Produto B'), ["Produto 0,5 MG", "Produto B"])

    def test_invalid_records_do_not_silently_drop_items(self):
        for text in ('"aspas abertas', "A\nB", '"A"texto, B'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_weni_order_list(text)
        self.assertEqual(parse_weni_order_list("A, , B"), ["A", "", "B"])

    def test_payment_codes_preserve_int32_without_inventing_a_label(self):
        for value, expected in ((0, "0"), (6, "6"), ("009", "9"), (2147483647, "2147483647")):
            self.assertEqual(normalize_farmalider_payment_code(value), expected)
        for value in (True, None, -1, 1.5, "1.5", "Pix", "١", 2147483648):
            with self.subTest(value=value):
                self.assertEqual(normalize_farmalider_payment_code(value), "")
