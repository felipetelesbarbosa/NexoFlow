import json
import unittest

from analytics import (
    BI_ADS_COLUMNS,
    BI_CHANNEL_COLUMNS,
    BI_CONVERSION_COLUMNS,
    BI_ORDERS_COLUMNS,
    BI_SALES_COLUMNS,
    BI_STATUS_COLUMNS,
    BI_SUMMARY_COLUMNS,
    build_bi_ads_rows,
    build_bi_channel_records,
    build_bi_conversion_records,
    build_bi_order_rows,
    build_bi_sales_rows,
    build_bi_summary_record,
    build_sales_metrics,
    normalize_contact,
    parse_ultimo_pedido,
)
from config import (
    SHEET_BI_ADS,
    SHEET_BI_CANAIS,
    SHEET_BI_CONVERSAO,
    SHEET_BI_PEDIDOS,
    SHEET_BI_RESUMO_DIARIO,
    SHEET_BI_STATUS,
    SHEET_BI_VENDAS,
)
from google_sheets import GoogleSheetsStore
from main import split_contacts


class BILayerTests(unittest.TestCase):
    def test_normalized_contact_exposes_age_lgpd_fields(self) -> None:
        contact = {
            "uuid": "u1",
            "fields": {
                "idade": 27,
                "maior_de_18_anos": "sim",
                "opt_in_lgpd": "ativo",
            },
        }
        row = normalize_contact(contact, "2026-10-05T14:00:00+00:00")
        self.assertEqual(row["idade"], "27")
        self.assertEqual(row["maior_de_18_anos"], "sim")
        self.assertEqual(row["opt_in_lgpd"], "ativo")

    def test_analytics_keeps_plain_weni_contact_for_bi(self) -> None:
        contact = {"uuid": "plain", "fields": {}}
        relevant, with_cpf, to_process = split_contacts([contact])
        self.assertEqual(relevant, [])
        self.assertEqual(with_cpf, [])
        self.assertEqual(to_process, [contact])

    def test_bi_summary_and_channels_are_generated_without_sales(self) -> None:
        base = [
            {
                "contact_uuid": "u1",
                "cpf": "52998224725",
                "cpf_normalizado": "52998224725",
                "farmalider_cliente_status": "CPF_CONFIRMADO",
                "contact_canal_principal": "whatsapp",
                "opt_in_lgpd": "ativo",
                "maior_de_18_anos": "sim",
                "weni_created_on": "2026-10-05T10:00:00-03:00",
            },
            {
                "contact_uuid": "u2",
                "cpf": "",
                "contact_canal_principal": "instagram",
                "opt_in_lgpd": "recusado",
                "maior_de_18_anos": "não",
                "weni_created_on": "2026-10-04T10:00:00-03:00",
            },
        ]
        summary = build_bi_summary_record(
            base,
            [],
            [],
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        self.assertEqual(summary["contatos_total"], 2)
        self.assertEqual(summary["novos_contatos"], 1)
        self.assertEqual(summary["clientes_farmalider"], 1)
        self.assertEqual(summary["whatsapp"], 1)
        self.assertEqual(summary["instagram"], 1)
        self.assertEqual(summary["pedidos_dia"], 0)

        channels = build_bi_channel_records(
            base,
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        by_channel = {r["canal"]: r for r in channels}
        self.assertEqual(by_channel["whatsapp"]["contatos"], 1)
        self.assertEqual(by_channel["instagram"]["contatos"], 1)

    def test_bi_sales_emits_today_zero_row_before_first_sale(self) -> None:
        rows = build_bi_sales_rows(
            [],
            [],
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "2026-10-05")
        self.assertEqual(rows[0][1], 0)
        self.assertEqual(rows[0][5], 0.0)

    def test_bi_ads_emits_placeholder_before_first_attribution(self) -> None:
        rows = build_bi_ads_rows(
            [],
            [],
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "Sem dados")
        self.assertEqual(rows[0][7:12], ["", "", "", "", ""])

    def test_bi_conversion_has_four_contact_funnel_stages(self) -> None:
        base = [
            {
                "contact_uuid": "u1",
                "cpf": "52998224725",
                "farmalider_cliente_status": "CPF_CONFIRMADO",
            }
        ]
        rows = build_bi_conversion_records(
            base,
            [],
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        self.assertEqual([r["etapa_ordem"] for r in rows], [1, 2, 3, 4])
        self.assertEqual(rows[0]["quantidade"], 1)
        self.assertEqual(rows[2]["quantidade"], 1)
        self.assertEqual(rows[3]["quantidade"], 0)

    def test_google_sheets_schema_contains_all_bi_tabs(self) -> None:
        schema = GoogleSheetsStore._schema_map()
        self.assertEqual(schema[SHEET_BI_RESUMO_DIARIO], BI_SUMMARY_COLUMNS)
        self.assertEqual(schema[SHEET_BI_CANAIS], BI_CHANNEL_COLUMNS)
        self.assertEqual(schema[SHEET_BI_CONVERSAO], BI_CONVERSION_COLUMNS)
        self.assertEqual(schema[SHEET_BI_VENDAS], BI_SALES_COLUMNS)
        self.assertEqual(schema[SHEET_BI_ADS], BI_ADS_COLUMNS)
        self.assertEqual(schema[SHEET_BI_PEDIDOS], BI_ORDERS_COLUMNS)
        self.assertEqual(schema[SHEET_BI_STATUS], BI_STATUS_COLUMNS)

    def test_bi_orders_exposes_friendly_order_contract(self) -> None:
        base = [
            {
                "contact_uuid": "u1",
                "nome": "Cliente",
                "cpf_normalizado": "52998224725",
                "contact_canal_principal": "whatsapp",
            }
        ]
        orders = [
            {
                "pedido_chave": "FARMALIDER:340793",
                "pedido_id": "340793",
                "data_hora": "2026-06-05T15:45:27-03:00",
                "contact_uuid": "u1",
                "cliente": "Cliente",
                "cpf_normalizado": "52998224725",
                "valor_total_compra": "112.80",
                "farmalider_frete": "9.90",
                "valor_total_faturamento": "122.70",
                "farmalider_status_pedido": "3",
                "farmalider_forma_pagamento": "2",
            }
        ]
        items = [
            {
                "pedido_chave": "FARMALIDER:340793",
                "produto_ordem": "1",
                "produto_nome": "PROLOPA BD 100+25MG C/30CAP",
                "quantidade": "1",
                "valor_unitario": "53.90",
            },
            {
                "pedido_chave": "FARMALIDER:340793",
                "produto_ordem": "2",
                "produto_nome": "TP PRAMIPEXOL PRATI 1MG C/30 CPR (G)",
                "quantidade": "1",
                "valor_unitario": "58.90",
            },
        ]
        rows = build_bi_order_rows(
            base,
            orders,
            items,
            updated_at="2026-10-06T21:00:00-03:00",
        )
        self.assertEqual(len(rows), 1)
        record = dict(zip(BI_ORDERS_COLUMNS, rows[0], strict=False))
        self.assertEqual(record["pedido_data"], "05/06/26 15:45:27")
        self.assertEqual(
            record["pedido_produtos"],
            "PROLOPA BD 100+25MG C/30CAP, TP PRAMIPEXOL PRATI 1MG C/30 CPR (G)",
        )
        self.assertEqual(record["pedido_quantidade_itens"], "1, 1")
        self.assertEqual(record["pedido_valor_produtos"], "53.9, 58.9")
        self.assertEqual(record["pedido_valor"], 112.8)
        self.assertEqual(record["pedido_frete"], 9.9)
        self.assertEqual(record["pedido_faturamento_total"], 122.7)
        self.assertEqual(record["pedido_status"], "3")
        self.assertEqual(record["pedido_status_nome"], "Cancelado")
        self.assertEqual(record["pedido_forma_pagamento"], "2")
        self.assertEqual(record["pedido_forma_pagamento_nome"], "Débito")

    def order_fixture(
        self, *, confirmation="CONFIRMADO_API", cancellation="", status=2
    ):
        raw = json.dumps(
            {
                "pedido_id": "500",
                "data_hora": "2026-10-05T10:00:00-03:00",
                "valor_total_compra": "19.50",
                "produtos": [
                    {
                        "nome": "Produto sintético",
                        "codigo": "900",
                        "quantidade": 2,
                        "valor_unitario": "10.00",
                        "valor_total": "19.50",
                    }
                ],
                "status_confirmacao": confirmation,
                "farmalider_cancelamento": cancellation,
                "farmalider_status_pedido": status,
            }
        )
        order, items = parse_ultimo_pedido(
            {"uuid": "u1", "fields": {"ultimo_pedido": raw}}, "2026-10-05T14:00:00Z"
        )
        order["primeiro_anuncio_id"] = "test-ad"
        order["primeiro_anuncio_titulo"] = "Anúncio sintético"
        base = [
            {
                "contact_uuid": "u1",
                "primeiro_anuncio_id": "test-ad",
                "primeiro_anuncio_titulo": "Anúncio sintético",
            }
        ]
        return base, order, items

    def test_cancelled_and_mismatched_orders_remain_auditable_but_leave_all_sales_kpis(
        self,
    ):
        cases = (
            {"cancellation": "2026-10-05T11:00:00-03:00"},
            {"status": "CANCELADO", "cancellation": "false"},
            {"status": 3, "cancellation": ""},
            {"status": "3", "cancellation": "false"},
            {"confirmation": "CANCELADO_API"},
            {"confirmation": "NAO_CONFIRMADO_API"},
            {"confirmation": "PEDIDO_CLIENTE_DIVERGENTE_API"},
            {"confirmation": "PEDIDO_ID_DIVERGENTE_API"},
        )
        for case in cases:
            with self.subTest(case=case):
                base, order, items = self.order_fixture(**case)
                self.assertEqual(order["pedido_chave"], "FARMALIDER:500")
                self.assertEqual(len(items), 1)
                self.assertEqual(build_sales_metrics([order], items), [])
                summary = build_bi_summary_record(
                    base,
                    [order],
                    items,
                    snapshot_date="2026-10-05",
                    updated_at="2026-10-05T14:00:00Z",
                )
                for key in (
                    "pedidos_total",
                    "faturamento_total",
                    "clientes_compradores_total",
                    "pedidos_dia",
                    "faturamento_dia",
                    "unidades_vendidas_dia",
                ):
                    self.assertEqual(summary[key], 0)
                conversion = build_bi_conversion_records(
                    base,
                    [order],
                    snapshot_date="2026-10-05",
                    updated_at="2026-10-05T14:00:00Z",
                )
                self.assertEqual(conversion[-1]["quantidade"], 0)
                ads = build_bi_ads_rows(
                    base,
                    [order],
                    snapshot_date="2026-10-05",
                    updated_at="2026-10-05T14:00:00Z",
                )
                self.assertEqual(ads[0][7], 1)
                self.assertEqual(ads[0][9:12], [0, 0, 0.0])

    def test_false_cancellation_and_completed_status_do_not_remove_valid_sales(self):
        for cancellation in (False, "False", "false", 0, "0", "null", None):
            with self.subTest(cancellation=cancellation):
                _, order, items = self.order_fixture(
                    cancellation=cancellation, status=2
                )
                self.assertEqual(
                    build_sales_metrics([order], items),
                    [["2026-10-05", 1, 1, 1, "2", "19.50", "0.00", "19.50", "19.50"]],
                )

    def test_new_contacts_use_business_day_at_utc_midnight(self):
        base = [{"contact_uuid": "u1", "weni_created_on": "2026-10-06T01:30:00Z"}]
        summary = build_bi_summary_record(
            base, [], [], snapshot_date="2026-10-05", updated_at="2026-10-06T01:30:00Z"
        )
        self.assertEqual(summary["novos_contatos"], 1)

    def test_configured_states_enter_sales_and_bi(self):
        for status in (
            -2,
            -1,
            0,
            1,
            2,
            3,
            4,
            "-2",
            "-1",
            "0",
            "1",
            "2",
            "3",
            "4",
            "99",
            "",
            None,
        ):
            with self.subTest(status=status):
                base, order, items = self.order_fixture(status=status)
                made = str(status) in {"4", "1", "2"}
                self.assertEqual(len(items), 1)  # Every state remains auditable.
                self.assertEqual(order["pedido_chave"], "FARMALIDER:500")
                expected_sales = (
                    [["2026-10-05", 1, 1, 1, "2", "19.50", "0.00", "19.50", "19.50"]]
                    if made
                    else []
                )
                self.assertEqual(build_sales_metrics([order], items), expected_sales)
                summary = build_bi_summary_record(
                    base,
                    [order],
                    items,
                    snapshot_date="2026-10-05",
                    updated_at="2026-10-05T14:00:00Z",
                )
                for key in (
                    "pedidos_total",
                    "clientes_compradores_total",
                    "pedidos_dia",
                    "clientes_compradores_dia",
                ):
                    self.assertEqual(summary[key], 1 if made else 0)
                for key in (
                    "faturamento_total",
                    "faturamento_dia",
                    "faturamento_confirmado_api_dia",
                ):
                    self.assertEqual(summary[key], 19.50 if made else 0)
                self.assertEqual(summary["unidades_vendidas_dia"], 2 if made else 0)
                conversion = build_bi_conversion_records(
                    base,
                    [order],
                    snapshot_date="2026-10-05",
                    updated_at="2026-10-05T14:00:00Z",
                )
                self.assertEqual(conversion[-1]["quantidade"], 1 if made else 0)
                ads = build_bi_ads_rows(
                    base,
                    [order],
                    snapshot_date="2026-10-05",
                    updated_at="2026-10-05T14:00:00Z",
                )
                self.assertEqual(ads[0][9:12], [1, 1, 19.5] if made else [0, 0, 0.0])


if __name__ == "__main__":
    unittest.main()
# NexoFlow 1.0
