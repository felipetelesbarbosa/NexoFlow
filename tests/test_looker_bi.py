"""KPIs comerciais: dados fictícios, sem rede, CPF ou segredos reais."""

import copy
import unittest
from datetime import date
from unittest.mock import Mock, patch

from analytics import (
    BI_SUMMARY_COLUMNS,
    bi_customer_key,
    build_sales_metrics,
    normalize_contact,
)
from google_sheets import GoogleSheetsStore
from looker_bi import SCHEMAS, build_looker_tables


def order(
    number, customer="10", uuid="u1", day="2026-10-01", revenue="100", status="2"
):
    return {
        "pedido_chave": f"FARMALIDER:{number}",
        "pedido_id": str(number),
        "farmalider_cliente_id": customer,
        "contact_uuid": uuid,
        "cliente": "Nome igual",
        "data": day,
        "data_hora": day + "T12:00:00-03:00",
        "status_confirmacao": "CONFIRMADO_API",
        "status_validacao": "OK",
        "farmalider_status_pedido": status,
        "farmalider_forma_pagamento": "3",
        "valor_total_compra": revenue,
        "valor_total_faturamento": revenue,
        "farmalider_frete": "0",
    }


def item(number, product="SKU1", revenue="100", position=1, quantity="1"):
    return {
        "item_chave": f"FARMALIDER:{number}:{position}",
        "pedido_chave": f"FARMALIDER:{number}",
        "produto_codigo": product,
        "produto_nome": "Produto " + product,
        "quantidade": quantity,
        "valor_unitario": revenue,
        "valor_total": revenue,
    }


def records(tables, name):
    return [dict(zip(SCHEMAS[name], row, strict=True)) for row in tables[name]]


class LookerBITests(unittest.TestCase):
    def build(self, orders=None, items=None, base=None, **options):
        return build_looker_tables(
            base or [],
            orders or [],
            items or [],
            snapshot_date="2026-10-11",
            updated_at="2026-10-11T12:00:00-03:00",
            period_start="2026-10-01",
            period_end="2026-10-11",
            **options,
        )

    def test_same_person_accumulates_orders_across_dates_and_contacts(self):
        tables = self.build(
            [order(1), order(2, uuid="u2", day="2026-10-09", revenue="50")]
        )
        customer = records(tables, "BI_Clientes")[0]
        self.assertEqual(customer["pedidos_identificados"], 2)
        self.assertEqual(customer["faturamento_identificado"], 150)
        self.assertEqual(customer["ultima_compra_identificada"], "2026-10-09")
        kpi = records(tables, "BI_KPIs_Periodo")[0]
        self.assertEqual(kpi["clientes_compradores"], 1)
        self.assertEqual(kpi["pedidos_por_cliente"], 2)
        self.assertEqual(kpi["ticket_medio"], 75)
        self.assertEqual(kpi["receita_media_por_cliente"], 150)

    def test_homonyms_remain_different_people(self):
        tables = self.build([order(1), order(2, customer="20", uuid="u2")])
        self.assertEqual(len(tables["BI_Clientes"]), 2)
        self.assertEqual(
            records(tables, "BI_KPIs_Periodo")[0]["clientes_compradores"], 2
        )

    def test_customer_key_does_not_depend_on_name_or_date_and_has_uuid_fallback(self):
        self.assertEqual(
            bi_customer_key(order(1)), bi_customer_key(order(2, day="2026-10-10"))
        )
        self.assertNotEqual(
            bi_customer_key(order(1, customer="")),
            bi_customer_key(order(1, customer="", uuid="u2")),
        )
        self.assertEqual(bi_customer_key({}, {}), "")

    def test_only_sales_enter_commercial_facts(self):
        for status in ("-2", "-1", "0", "3", "99"):
            with self.subTest(status=status):
                tables = self.build([order(1, status=status)], [item(1)])
                self.assertEqual(tables["BI_Clientes_Vendas"], [])
                self.assertEqual(tables["BI_Itens"], [])
        sale = order(1)
        sale["farmalider_forma_pagamento"] = "0"
        self.assertEqual(self.build([sale])["BI_Clientes_Vendas"], [])

    def test_duplicate_records_do_not_multiply_sales_and_conflicts_block(self):
        o, i = order(1), item(1)
        self.assertEqual(len(self.build([o, o], [i, i])["BI_Itens"]), 1)
        with self.assertRaises(ValueError):
            self.build([o, {**o, "valor_total_compra": "999"}])

    def test_no_personal_identifiers_or_payment_or_status_in_new_tables(self):
        for headers in SCHEMAS.values():
            for forbidden in (
                "cpf",
                "cpf_normalizado",
                "telefone",
                "email",
                "contact_uuid",
                "farmalider_cliente_id",
                "pedido_id",
                "pedido_status",
                "pedido_forma_pagamento",
            ):
                self.assertNotIn(forbidden, headers)
        key = records(self.build([order(321)]), "BI_Clientes_Vendas")[0]["venda_chave"]
        self.assertEqual(len(key), 32)
        self.assertNotIn("FARMALIDER", key)

    def test_product_revenue_excludes_freight_and_never_duplicates_order_total(self):
        o = order(1, revenue="120")
        o["farmalider_frete"] = "20"
        o["valor_total_compra"] = "100"
        tables = self.build([o], [item(1, "A", "40"), item(1, "B", "60", 2)])
        self.assertEqual(
            sum(r["receita_item"] for r in records(tables, "BI_Itens")), 100
        )
        kpi = records(tables, "BI_KPIs_Periodo")[0]
        self.assertEqual(kpi["faturamento_produtos"], 100)
        self.assertEqual(kpi["frete"], 20)
        self.assertEqual(kpi["faturamento"], 120)

    def test_abc_and_top5_use_all_products_before_limiting(self):
        orders = [order(n, revenue="10") for n in range(1, 11)]
        items = [item(n, str(n), "10") for n in range(1, 11)]
        tables = self.build(orders, items)
        products = records(tables, "BI_Produtos_ABC")
        self.assertEqual(len(products), 10)
        self.assertEqual(products[-1]["participacao_acumulada_pct"], 100)
        self.assertTrue(all(r["participacao_receita_pct"] == 10 for r in products))
        self.assertTrue(all(r["ranking_receita"] == 1 for r in products))
        self.assertEqual(
            records(tables, "BI_KPIs_Periodo")[0]["participacao_top5_receita_pct"], 50
        )

    def test_abc_classes_include_boundary_crossing_product(self):
        revenues = ["70", "20", "6", "4"]
        tables = self.build(
            [order(n, revenue=v) for n, v in enumerate(revenues, 1)],
            [item(n, str(n), v) for n, v in enumerate(revenues, 1)],
        )
        self.assertEqual(
            [r["classe_abc"] for r in records(tables, "BI_Produtos_ABC")],
            ["A", "A", "B", "C"],
        )

    def test_pairs_count_distinct_orders_not_item_combinations(self):
        tables = self.build(
            [order(1), order(2)],
            [
                item(1, "A", position=1),
                item(1, "A", position=2),
                item(1, "B", position=3),
                item(2, "A", position=1),
                item(2, "B", position=2),
            ],
        )
        self.assertEqual(len(tables["BI_Produtos_Juntos"]), 1)
        self.assertEqual(records(tables, "BI_Produtos_Juntos")[0]["pedidos_juntos"], 2)

    def test_period_limits_abc_and_kpis_but_not_filterable_history(self):
        tables = self.build(
            [order(1, day="2026-09-01"), order(2)], [item(1, "A"), item(2, "B")]
        )
        self.assertEqual(len(tables["BI_Clientes_Vendas"]), 2)
        self.assertEqual(records(tables, "BI_KPIs_Periodo")[0]["pedidos"], 1)
        self.assertEqual(len(tables["BI_Produtos_ABC"]), 1)

    def test_unknown_history_never_enables_comparison_or_repurchase(self):
        tables = self.build([order(1), order(2)], history_observed_since="2026-10-01")
        quality = records(tables, "BI_Qualidade")[0]
        for key in (
            "historico_completo",
            "recompra_disponivel",
            "comparacao_disponivel",
        ):
            self.assertEqual(quality[key], 0)
        self.assertEqual(
            records(tables, "BI_KPIs_Periodo")[0]["variacao_pedidos_pct"], ""
        )

    def test_gender_is_explicit_optional_and_age_zero_is_informed(self):
        base = [
            normalize_contact(
                {
                    "uuid": "u1",
                    "name": "Nome qualquer",
                    "fields": {"genero": "Não informado", "idade": 0},
                },
                "now",
            ),
            normalize_contact({"uuid": "u2", "name": "Maria", "fields": {}}, "now"),
        ]
        public = records(self.build(base=base), "BI_Publico")
        self.assertEqual(public[0]["genero"], "Não informado")
        self.assertEqual(public[1]["genero"], "")
        self.assertEqual(public[0]["idade_informada"], 1)
        self.assertEqual(public[1]["idade_informada"], 0)

    def test_unknown_sku_or_category_is_not_invented(self):
        tables = self.build([order(1)], [item(1, product="")])
        product = records(tables, "BI_Produtos_ABC")[0]
        self.assertEqual(product["categoria"], "")
        self.assertEqual(product["classe_abc"], "")
        self.assertEqual(product["abc_disponivel"], 0)
        self.assertEqual(records(tables, "BI_KPIs_Periodo")[0]["skus_distintos"], 0)

    def test_invalid_numeric_item_blocks_instead_of_becoming_zero(self):
        for value in ("NaN", "lixo", "-10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.build([order(1)], [item(1, revenue=value)])

    def test_empty_period_has_absent_rates_not_division_by_zero(self):
        kpi = records(self.build(), "BI_KPIs_Periodo")[0]
        self.assertEqual(kpi["pedidos"], 0)
        self.assertEqual(kpi["ticket_medio"], "")
        self.assertEqual(kpi["participacao_top5_receita_pct"], "")

    def test_daily_sales_count_verified_customer_not_weni_duplicates(self):
        self.assertEqual(
            build_sales_metrics([order(1), order(2, uuid="u2")], [])[0][3], 1
        )

    def test_invalid_period_rejected_before_network(self):
        from run_looker import run

        with self.assertRaises(ValueError):
            run(["--inicio", "2026-10-11", "--fim", "2026-10-01"])


class TypedSheetTests(unittest.TestCase):
    def test_rebuild_uses_stored_history_and_closes_sheet_connection(self):
        from run_looker import run

        store = Mock()
        store.load_base_snapshot.return_value = ([], [], {})
        store.load_order_records.return_value = [order(1)]
        store.load_order_item_records.return_value = []
        store.get_control.return_value = "2026-10-01"
        with (
            patch("google_sheets.GoogleSheetsStore", return_value=store),
            patch("proxy_config.configure_proxy"),
            patch("logging_config.configure_logging"),
        ):
            self.assertEqual(run(["--inicio", "2026-10-01", "--fim", "2026-10-01"]), 0)
        tables = store.replace_looker_tables.call_args.args[0]
        self.assertEqual(set(tables), set(SCHEMAS))
        self.assertEqual(len(tables["BI_Clientes_Vendas"]), 1)
        store.migrate_bi_summary_numbers.assert_called_once_with()
        store.close.assert_called_once_with()

    def test_looker_dates_numbers_and_formula_like_names_are_literal_raw_values(self):
        headers = SCHEMAS["BI_Itens"]
        row = [
            "i",
            "o",
            "c",
            "2026-10-01",
            "001",
            "=1+1",
            "",
            2.5,
            19.5,
            48.75,
            1,
            "now",
        ]
        written = GoogleSheetsStore._typed_bi_rows(headers, [row])[0]
        self.assertEqual(written[3], (date(2026, 10, 1) - date(1899, 12, 30)).days)
        self.assertEqual(written[4], "001")
        self.assertEqual(written[5], "=1+1")
        self.assertIsInstance(written[9], float)

    def test_migration_keeps_physical_column_order_and_historical_rows(self):
        headers = BI_SUMMARY_COLUMNS[:]
        headers.remove("faturamento_dia")
        headers.append("faturamento_dia")
        old = {
            "data": "2026-10-09",
            "atualizado_em": "old",
            "faturamento_dia": "1170.06",
        }
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._headers_cache = {}
        store.get_control = Mock(return_value="")
        store.bi_summary = Mock(title="BI_Resumo_Diario", row_count=100)
        store.bi_summary.get_all_values.return_value = [
            headers,
            [old.get(h, "") for h in headers],
        ]
        store._read_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._replace_table = Mock()
        store._format_bi_columns = Mock()
        store.set_controls = Mock()
        store.migrate_bi_summary_numbers()
        written_headers, rows = store._replace_table.call_args.args[1:]
        self.assertEqual(written_headers, headers)
        self.assertEqual(rows[0][-1], 1170.06)
        self.assertEqual(store._headers_cache["BI_Resumo_Diario"], headers)
        self.assertEqual(store._format_bi_columns.call_args.args[1], headers)
        store.set_controls.assert_called_once_with({"_bi_numeric_revision": "2"})

    def test_summary_uses_iso_key_and_native_amount_to_avoid_dates_and_duplicate_days(
        self,
    ):
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.migrate_bi_summary_numbers = Mock()
        store.bi_summary = Mock()
        store._upsert_records_detailed = Mock()
        source = {"data": "2026-10-09", "faturamento_dia": 1170.06}
        store.upsert_bi_summary(source)
        written = store._upsert_records_detailed.call_args.args[1][0]
        self.assertEqual(written["data"], "2026-10-09")
        self.assertEqual(written["faturamento_dia"], 1170.06)
        self.assertTrue(
            store._upsert_records_detailed.call_args.kwargs["preserve_types"]
        )

    def test_historical_orders_are_preserved_when_new_order_arrives_and_repeat_is_idempotent(
        self,
    ):
        headers = ["pedido_chave", "contact_uuid", "valor_total_compra"]
        values = [headers, ["FARMALIDER:1", "u1", "10"]]
        ws = Mock(title="Pedidos_FarmaLider")
        ws.get_all_values.side_effect = lambda: copy.deepcopy(values)
        ws.append_rows.side_effect = lambda rows, **kwargs: values.extend(
            copy.deepcopy(rows)
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._read_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        incoming = [
            {
                "pedido_chave": "FARMALIDER:2",
                "contact_uuid": "u1",
                "valor_total_compra": "20",
            }
        ]
        first = store._upsert_records_detailed(ws, incoming, "pedido_chave")
        self.assertEqual(len(first.final_records), 2)
        self.assertEqual(
            store._upsert_records_detailed(ws, incoming, "pedido_chave").inserted, 0
        )
        self.assertEqual(len(values), 3)

    def test_batched_replacement_ranges_are_contiguous(self):
        ws = Mock(title="BI_Itens", row_count=100, col_count=2)
        ws.get_all_values.return_value = []
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store._read_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        store._write_with_retry = Mock(
            side_effect=lambda description, operation: operation()
        )
        with patch("google_sheets.GOOGLE_SHEETS_APPEND_BATCH_SIZE", 2):
            store._replace_table(ws, ["a", "b"], [[1, 2], [3, 4], [5, 6]])
        self.assertEqual(
            [c.kwargs["range_name"] for c in ws.update.call_args_list],
            ["A1:B2", "A3:B4"],
        )
