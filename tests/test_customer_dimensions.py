"""Dimensões de cliente e datas enviadas ao Sheets, sem integrações externas."""

import unittest
from datetime import date
from unittest.mock import Mock

from analytics import (
    BASE_COLUMNS,
    BI_ORDERS_COLUMNS,
    HISTORY_COLUMNS,
    build_bi_order_rows,
    normalize_contact,
)
from google_sheets import GoogleSheetsStore


class CustomerDimensionsTests(unittest.TestCase):
    def test_profile_keeps_location_postcode_and_age(self):
        row = normalize_contact(
            {
                "uuid": "u1",
                "created_on": "2026-10-09T01:30:00Z",
                "fields": {
                    "cidade": "Belém",
                    "bairro": "Nazaré",
                    "estado": "PA",
                    "cep": "01234-567",
                    "idade": 37,
                },
            },
            "2026-10-10T09:00:00-03:00",
        )
        self.assertEqual(
            {k: row[k] for k in ("cidade", "bairro", "estado", "cep", "idade")},
            {
                "cidade": "Belém",
                "bairro": "Nazaré",
                "estado": "Pará",
                "cep": "01234-567",
                "idade": "37",
            },
        )
        for column in ("cidade", "bairro", "estado", "cep", "idade"):
            self.assertIn(column, BASE_COLUMNS)
            self.assertIn(column, HISTORY_COLUMNS)
        self.assertEqual(HISTORY_COLUMNS.count("sincronizado_em"), 1)

    def test_missing_profile_is_absence(self):
        row = normalize_contact(
            {"uuid": "u1", "created_on": "invalid", "fields": {}},
            "2026-10-09T10:00:00-03:00",
        )
        for column in ("cidade", "bairro", "estado", "cep", "idade"):
            self.assertEqual(row[column], "")

    def build_order(self, base):
        rows = build_bi_order_rows(
            base,
            [
                {
                    "pedido_chave": "FARMALIDER:1",
                    "pedido_id": "1",
                    "contact_uuid": "u1",
                    "data_hora": "2026-06-05T15:45:27-03:00",
                    "cpf_normalizado": "52998224725",
                    "valor_total_compra": "10",
                    "farmalider_status_pedido": "2",
                    "farmalider_forma_pagamento": "3",
                }
            ],
            [],
            updated_at="2026-10-09T10:00:00-03:00",
        )
        self.assertEqual(len(rows), 1)
        return rows, dict(zip(BI_ORDERS_COLUMNS, rows[0], strict=False))

    def test_order_joins_its_customer_only_and_keeps_order_date_distinct_from_sync(
        self,
    ):
        _, row = self.build_order(
            [
                {
                    "contact_uuid": "u2",
                    "cidade": "Outra cidade",
                    "cep": "99999999",
                    "idade": "99",
                },
                {
                    "contact_uuid": "u1",
                    "cidade": "Belém",
                    "bairro": "Nazaré",
                    "estado": "PA",
                    "cep": "01234567",
                    "idade": "37",
                },
            ]
        )
        self.assertEqual(row["cidade"], "Belém")
        self.assertEqual(row["cep"], "01234567")
        self.assertEqual(row["idade"], 37)
        self.assertEqual(row["data"], "2026-06-05")
        self.assertEqual(row["pedido_data"], "05/06/26 15:45:27")
        self.assertEqual(row["atualizado_em"], "2026-10-09T10:00:00-03:00")

    def test_unknown_contact_and_invalid_age_stay_empty(self):
        _, row = self.build_order(
            [{"contact_uuid": "unrelated", "cidade": "Cidade diferente", "idade": "40"}]
        )
        for column in ("cidade", "bairro", "estado", "cep", "idade"):
            self.assertEqual(row[column], "")
        for age in ("", "null", "NaN", "-1", "37.5"):
            with self.subTest(age=age):
                _, row = self.build_order([{"contact_uuid": "u1", "idade": age}])
                self.assertEqual(row["idade"], "")
        _, row = self.build_order([{"contact_uuid": "u1", "idade": "0"}])
        self.assertEqual(row["idade"], 0)

    def test_sheets_preserves_postcode_zeros_and_location_as_literal_text(self):
        rows, _ = self.build_order(
            [
                {
                    "contact_uuid": "u1",
                    "cep": "01234567",
                    "cidade": "=1+1",
                    "bairro": "Nazaré",
                    "estado": "PA",
                    "idade": "37",
                }
            ]
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.bi_orders = Mock()
        store._replace_table = Mock()
        store._format_bi_columns = Mock()
        store.replace_bi_orders(rows)
        written = dict(
            zip(
                BI_ORDERS_COLUMNS,
                store._replace_table.call_args.args[2][0],
                strict=False,
            )
        )
        self.assertEqual(written["cep"], "01234567")
        self.assertEqual(written["cidade"], "=1+1")
        self.assertEqual(written["idade"], 37)
        self.assertEqual(written["data"], (date(2026, 6, 5) - date(1899, 12, 30)).days)
        self.assertEqual(rows[0][BI_ORDERS_COLUMNS.index("cep")], "01234567")


if __name__ == "__main__":
    unittest.main()
