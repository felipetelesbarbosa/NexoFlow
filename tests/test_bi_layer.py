import unittest

from analytics import (
    BI_ADS_COLUMNS,
    BI_CHANNEL_COLUMNS,
    BI_CONVERSION_COLUMNS,
    BI_SALES_COLUMNS,
    BI_STATUS_COLUMNS,
    BI_SUMMARY_COLUMNS,
    build_bi_ads_rows,
    build_bi_channel_records,
    build_bi_conversion_records,
    build_bi_sales_rows,
    build_bi_summary_record,
    normalize_contact,
)
from config import (
    SHEET_BI_ADS,
    SHEET_BI_CANAIS,
    SHEET_BI_CONVERSAO,
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
            base, [], [],
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
            [], [],
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "2026-10-05")
        self.assertEqual(rows[0][1], 0)
        self.assertEqual(rows[0][5], 0.0)

    def test_bi_ads_emits_placeholder_before_first_attribution(self) -> None:
        rows = build_bi_ads_rows(
            [], [],
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00+00:00",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], "Sem dados")
        self.assertEqual(rows[0][7], 0)

    def test_bi_conversion_has_four_contact_funnel_stages(self) -> None:
        base = [{"contact_uuid": "u1", "cpf": "52998224725", "farmalider_cliente_status": "CPF_CONFIRMADO"}]
        rows = build_bi_conversion_records(
            base, [],
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
        self.assertEqual(schema[SHEET_BI_STATUS], BI_STATUS_COLUMNS)


if __name__ == "__main__":
    unittest.main()
