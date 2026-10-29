"""Synthetic integration tests for the FarmaLíder-first order architecture."""

import json
import re
import unittest
from unittest.mock import Mock

from analytics import (
    BI_ORDERS_COLUMNS,
    ORDER_COLUMNS,
    ORDER_ITEM_COLUMNS,
    build_bi_conversion_records,
    build_bi_order_rows,
    build_bi_summary_record,
    build_sales_metrics,
    normalize_contact,
    parse_ultimo_pedido,
)
from google_sheets import GoogleSheetsStore
from main import FarmaliderSettings, build_orders, split_contacts, validate_contacts
from pedido_utils import serialize_pedido_products


class MemoryWorksheet:
    def __init__(self, title, headers):
        self.title = title
        self.row_count = 1000
        self.values = [list(headers)]

    def get_all_values(self):
        return [row[:] for row in self.values]

    def col_values(self, column):
        return [row[column - 1] if len(row) >= column else "" for row in self.values]

    def update(self, *, range_name, values, **kwargs):
        start = int(range_name.split(":", 1)[0].lstrip("A")) - 1
        while len(self.values) < start + len(values):
            self.values.append([])
        for offset, row in enumerate(values):
            self.values[start + offset] = list(row)

    def append_rows(self, rows, **kwargs):
        self.values.extend([row[:] for row in rows])

    def batch_update(self, updates, **kwargs):
        for update in updates:
            row = int(re.search(r"A(\d+):", update["range"])[1])
            self.values[row - 1] = update["values"][0][:]


class AnalyticsOrderFlowTests(unittest.TestCase):
    def fixture(self, *, status=2, cancelled=False, freight="9.99", payment=2):
        contact = {"uuid": "synthetic-u1", "fields": {"cpf": "52998224725"}}
        client = Mock()
        cliente_items = [
            {
                "codPedido": 500,
                "codProduto": 9001,
                "descricao": "Produto sintético",
                "quantidade": 2,
                "valor": "10.00",
                "total": "19.50",
            }
        ]
        client.get_cliente_by_cpf.return_value = {
            "cliente": {
                "id": 99,
                "cpf": "52998224725",
                "nome": "Cliente sintético",
            },
            "ultimoPedido": {
                "id": 500,
                "codCliente": 99,
                "emissao": "2026-10-05T10:00:00",
                "status": status,
                "formaPagamento": payment,
                "frete": freight,
                "cancelamento": ("2026-10-05T11:00:00" if cancelled else None),
            },
            "itens": cliente_items,
        }
        client.get_pedido.return_value = {
            "capa": {
                "id": 500,
                "codCliente": 99,
                "emissao": "2026-10-05T10:00:00",
                "status": status,
                "formaPagamento": payment,
                "frete": freight,
                "cancelamento": ("2026-10-05T11:00:00" if cancelled else None),
            },
            "itens": [dict(cliente_items[0])],
        }
        client.metrics_snapshot.return_value = {
            "total_requests": 1,
            "retries": 0,
            "rate_limits": 0,
            "server_errors": 0,
            "network_errors": 0,
            "average_response_ms": 1,
            "max_response_ms": 1,
            "effective_delay_ms": 0,
        }
        return contact, client

    def resolve_and_persist(self, contact, client):
        _, _, processed = split_contacts([contact])
        row = normalize_contact(contact, "2026-10-05T14:00:00Z")
        responses = {}
        validate_contacts(
            [row],
            farm_client=client,
            farm_settings=FarmaliderSettings(True, "synthetic-token", False),
            sync_time="2026-10-05T14:00:00Z",
            cliente_responses_by_cpf=responses,
        )
        orders, items, _ = build_orders(
            processed,
            rows_by_uuid={row["contact_uuid"]: row},
            farm_client=client,
            sync_time="2026-10-05T14:00:00Z",
            cliente_responses_by_cpf=responses,
        )
        store = GoogleSheetsStore.__new__(GoogleSheetsStore)
        store.orders = MemoryWorksheet("Pedidos", ORDER_COLUMNS)
        store.order_items = MemoryWorksheet("Itens_Pedido", ORDER_ITEM_COLUMNS)
        store._read_with_retry = lambda label, operation: operation()
        store._write_with_retry = lambda label, operation: operation()
        first = store.upsert_orders_detailed(orders)
        first_items = store.upsert_order_items_detailed(items)
        repeated = store.upsert_orders_detailed(orders)
        repeated_items = store.upsert_order_items_detailed(items)
        self.assertEqual(first.inserted, 1)
        self.assertEqual(repeated.inserted, 0)
        self.assertEqual(repeated.unchanged, 1)
        self.assertEqual(repeated_items.inserted, 0)
        self.assertEqual(repeated_items.unchanged, len(items))
        return row, repeated.final_records, first_items.final_records

    def test_normalized_contact_exposes_raw_status_payment_and_labels(self):
        contact = {
            "uuid": "u1",
            "fields": {
                "pedido_status": "3",
                "pedido_forma_pagamento": "2",
            },
        }
        row = normalize_contact(contact, "2026-10-05T14:00:00Z")
        self.assertEqual(row["pedido_status"], "3")
        self.assertEqual(row["pedido_status_nome"], "Cancelado")
        self.assertEqual(row["pedido_forma_pagamento"], "2")
        self.assertEqual(row["pedido_forma_pagamento_nome"], "Débito")

    def test_normalized_contact_identifies_undocumented_payment_codes(self):
        for code in (9, 2147483647):
            for value in (code, str(code)):
                with self.subTest(value=value):
                    row = normalize_contact(
                        {
                            "uuid": "u1",
                            "fields": {"pedido_forma_pagamento": value},
                        },
                        "2026-10-05T14:00:00Z",
                    )
                    self.assertEqual(row["pedido_forma_pagamento"], str(code))
                    self.assertEqual(
                        row["pedido_forma_pagamento_nome"],
                        f"Não identificado (código {code})",
                    )

    def test_normalized_contact_uses_validated_payment_labels(self):
        for code, label in (
            (0, "Cancelado"),
            (5, "Pix por Link de Pagamento"),
            (6, "Pix no POS"),
        ):
            with self.subTest(code=code):
                row = normalize_contact(
                    {"uuid": "u1", "fields": {"pedido_forma_pagamento": code}},
                    "2026-10-05T14:00:00Z",
                )
                self.assertEqual(
                    row["pedido_forma_pagamento"],
                    "Cancelado" if code == 0 else str(code),
                )
                self.assertEqual(row["pedido_forma_pagamento_nome"], label)
                if code == 0:
                    self.assertEqual(row["pedido_status"], "3")
                    self.assertEqual(row["pedido_status_nome"], "Cancelado")

    def test_normalized_contact_does_not_label_invalid_payment_values(self):
        for value in (None, "", " ", True, False, "Pix", -1, "-1", 2147483648):
            with self.subTest(value=value):
                row = normalize_contact(
                    {
                        "uuid": "u1",
                        "fields": {"pedido_forma_pagamento": value},
                    },
                    "2026-10-05T14:00:00Z",
                )
                self.assertEqual(row["pedido_forma_pagamento_nome"], "")

    def test_api_payment_code_and_display_persist_through_to_bi(self):
        expected = {
            0: "Cancelado",
            1: "Dinheiro",
            2: "Débito",
            3: "Crédito",
            4: "Ticket",
            5: "Pix por Link de Pagamento",
            6: "Pix no POS",
            9: "Não identificado (código 9)",
            2147483647: "Não identificado (código 2147483647)",
        }
        for code, label in expected.items():
            with self.subTest(code=code):
                contact, client = self.fixture(payment=code)
                row, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(orders[0]["farmalider_forma_pagamento"], str(code))
                self.assertEqual(orders[0]["farmalider_forma_pagamento_nome"], label)
                bi_rows = build_bi_order_rows(
                    [row], orders, items, updated_at="2026-10-05T14:00:00Z"
                )
                self.assertEqual(len(bi_rows), 1)
                bi_order = dict(zip(BI_ORDERS_COLUMNS, bi_rows[0], strict=True))
                self.assertEqual(bi_order["pedido_forma_pagamento"], str(code))
                self.assertEqual(bi_order["pedido_forma_pagamento_nome"], label)
                self.assertEqual(orders[0]["farmalider_status_pedido"], "2")
                if code == 0:
                    self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
                    self.assertEqual(
                        orders[0]["farmalider_status_pedido_nome"], "Cancelado"
                    )
                    self.assertEqual(bi_order["pedido_status"], "3")
                    self.assertEqual(bi_order["pedido_status_nome"], "Cancelado")
                    self.assertEqual(build_sales_metrics(orders, items), [])
                else:
                    self.assertEqual(orders[0]["status_confirmacao"], "CONFIRMADO_API")
                    self.assertEqual(bi_order["pedido_status"], "2")
                    self.assertEqual(len(build_sales_metrics(orders, items)), 1)

    def test_new_open_states_persist_to_bi_with_configured_sales(self):
        for status, label in ((-2, "Em aberto"), (4, "Pronto para rota")):
            with self.subTest(status=status):
                contact, client = self.fixture(status=status, payment=6)
                row, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(orders[0]["status_validacao"], "OK")
                self.assertEqual(orders[0]["farmalider_status_pedido"], str(status))
                bi_rows = build_bi_order_rows(
                    [row], orders, items, updated_at="2026-10-05T14:00:00Z"
                )
                bi_order = dict(zip(BI_ORDERS_COLUMNS, bi_rows[0], strict=True))
                self.assertEqual(bi_order["pedido_status"], str(status))
                self.assertEqual(bi_order["pedido_status_nome"], label)
                self.assertEqual(
                    len(build_sales_metrics(orders, items)),
                    int(status in (-2, -1, 0, 4, 1, 2)),
                )

    def test_pending_payment_order_is_preserved_in_bi_as_non_cancelled_sale(self):
        contact, client = self.fixture(status=-1, payment=6)
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["status_validacao"], "OK")
        self.assertNotEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(orders[0]["farmalider_status_pedido"], "-1")
        self.assertEqual(
            orders[0]["farmalider_status_pedido_nome"], "Pendente de pagamento"
        )
        self.assertEqual(len(build_sales_metrics(orders, items)), 1)
        bi_rows = build_bi_order_rows(
            [row], orders, items, updated_at="2026-10-05T14:00:00Z"
        )
        self.assertEqual(len(bi_rows), 1)
        bi_order = dict(zip(BI_ORDERS_COLUMNS, bi_rows[0], strict=True))
        self.assertEqual(bi_order["pedido_status"], "-1")
        self.assertEqual(bi_order["pedido_status_nome"], "Pendente de pagamento")
        self.assertEqual(bi_order["pedido_forma_pagamento"], "6")
        self.assertEqual(bi_order["pedido_forma_pagamento_nome"], "Pix no POS")

    def test_payment_zero_overrides_pending_status_in_persisted_order_and_bi(self):
        contact, client = self.fixture(status=-1, payment=0)
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["farmalider_status_pedido"], "-1")
        self.assertEqual(orders[0]["farmalider_status_pedido_nome"], "Cancelado")
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(build_sales_metrics(orders, items), [])
        bi_rows = build_bi_order_rows(
            [row], orders, items, updated_at="2026-10-05T14:00:00Z"
        )
        self.assertEqual(len(bi_rows), 1)
        bi_order = dict(zip(BI_ORDERS_COLUMNS, bi_rows[0], strict=True))
        self.assertEqual(bi_order["pedido_status"], "3")
        self.assertEqual(bi_order["pedido_forma_pagamento"], "0")
        self.assertEqual(bi_order["pedido_forma_pagamento_nome"], "Cancelado")

    def test_cancelled_payment_round_trips_through_serialized_weni_snapshot(self):
        contact, client = self.fixture(status=2, payment=0)
        _, orders, items = self.resolve_and_persist(contact, client)
        contact["fields"]["ultimo_pedido"] = serialize_pedido_products(orders[0], items)
        restored, restored_items = parse_ultimo_pedido(contact, "2026-10-05T15:00:00Z")
        self.assertEqual(restored["farmalider_status_pedido"], "2")
        self.assertEqual(restored["farmalider_forma_pagamento"], "0")
        self.assertEqual(restored["farmalider_forma_pagamento_nome"], "Cancelado")
        self.assertEqual(restored["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(restored["farmalider_status_pedido_nome"], "Cancelado")
        self.assertEqual(build_sales_metrics([restored], restored_items), [])

    def test_missing_api_payment_does_not_invent_payment_in_orders_or_bi(self):
        for missing in (False, True):
            with self.subTest(field_missing=missing):
                contact, client = self.fixture(payment=None)
                if missing:
                    del client.get_cliente_by_cpf.return_value["ultimoPedido"][
                        "formaPagamento"
                    ]
                    del client.get_pedido.return_value["capa"]["formaPagamento"]
                row, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(orders[0]["farmalider_forma_pagamento"], "")
                self.assertEqual(orders[0]["farmalider_forma_pagamento_nome"], "")
                bi_rows = build_bi_order_rows(
                    [row], orders, items, updated_at="2026-10-05T14:00:00Z"
                )
                self.assertEqual(len(bi_rows), 1)
                bi_order = dict(zip(BI_ORDERS_COLUMNS, bi_rows[0], strict=True))
                self.assertEqual(bi_order["pedido_forma_pagamento"], "")
                self.assertEqual(bi_order["pedido_forma_pagamento_nome"], "")

    def test_cpf_contact_uses_description_and_item_total_without_freight(self):
        contact, client = self.fixture()
        row, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["pedido_chave"], "FARMALIDER:500")
        self.assertEqual(orders[0]["valor_total_compra"], "19.50")
        self.assertEqual(orders[0]["valor_total_faturamento"], "29.49")
        self.assertEqual(orders[0]["valor_origem"], "SOMA_ITENS_API")
        self.assertEqual(orders[0]["farmalider_frete"], "9.99")
        self.assertEqual(orders[0]["farmalider_forma_pagamento"], "2")
        self.assertEqual(orders[0]["farmalider_forma_pagamento_nome"], "Débito")
        self.assertEqual(items[0]["produto_codigo"], "9001")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        self.assertEqual(
            build_sales_metrics(orders, items),
            [["2026-10-05", 1, 1, 1, "2", "19.50", "9.99", "29.49", "29.49"]],
        )
        summary = build_bi_summary_record(
            [row],
            orders,
            items,
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00Z",
        )
        self.assertEqual(summary["faturamento_produtos_total"], 19.5)
        self.assertEqual(summary["faturamento_frete_total"], 9.99)
        self.assertEqual(summary["faturamento_total"], 29.49)
        self.assertEqual(summary["faturamento_total_dia"], 29.49)
        self.assertEqual(summary["unidades_vendidas_dia"], 2)

    def test_api_first_ignores_stale_weni_order_identity(self):
        contact, client = self.fixture()
        contact["fields"]["ultimo_pedido"] = json.dumps(
            {
                "pedido_id": "400",
                "data_hora": "2026-10-01T10:00:00-03:00",
                "valor_total_compra": "1.00",
                "produtos": [
                    {
                        "nome": "Pedido antigo",
                        "quantidade": 1,
                        "valor_unitario": 1,
                        "valor_total": 1,
                    }
                ],
            }
        )
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["pedido_id"], "500")
        self.assertEqual(items[0]["produto_nome"], "Produto sintético")
        client.get_cliente_by_cpf.assert_called_once_with("52998224725")
        client.get_pedido.assert_called_once_with("500")

    def test_pedido_endpoint_description_is_final_product_name(self):
        contact, client = self.fixture()
        client.get_cliente_by_cpf.return_value["itens"][0]["descricao"] = (
            "Descrição do GET CPF"
        )
        client.get_pedido.return_value["itens"][0]["descricao"] = (
            "Descrição atual do GET pedido"
        )
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["status_validacao"], "OK")
        self.assertEqual(items[0]["produto_nome"], "Descrição atual do GET pedido")

    def test_missing_description_rejects_pedido_snapshot(self):
        contact, client = self.fixture()
        del client.get_pedido.return_value["itens"][0]["descricao"]
        del client.get_cliente_by_cpf.return_value["itens"][0]["descricao"]
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(items, [])
        self.assertTrue(not orders or orders[0]["status_validacao"] == "ERRO")

    def test_cancelled_latest_order_is_auditable_but_not_sale(self):
        contact, client = self.fixture(status=3, cancelled=True)
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(orders[0]["status_confirmacao"], "CANCELADO_API")
        self.assertEqual(orders[0]["farmalider_status_pedido"], "3")
        self.assertEqual(build_sales_metrics(orders, items), [])
        conversion = build_bi_conversion_records(
            [],
            orders,
            snapshot_date="2026-10-05",
            updated_at="2026-10-05T14:00:00Z",
        )
        self.assertEqual(conversion[-1]["quantidade"], 0)

    def test_configured_states_enter_sales(self):
        for status in (-2, -1, 0, 1, 2, 4):
            with self.subTest(status=status):
                contact, client = self.fixture(status=status)
                _, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(
                    len(build_sales_metrics(orders, items)),
                    int(status in (-2, -1, 0, 4, 1, 2)),
                )

    def test_cancelled_and_unknown_states_stay_out_of_sales(self):
        for status in (3, 99):
            with self.subTest(status=status):
                contact, client = self.fixture(status=status)
                _, orders, items = self.resolve_and_persist(contact, client)
                self.assertEqual(build_sales_metrics(orders, items), [])

    def test_repeated_product_descriptions_keep_distinct_items(self):
        contact, client = self.fixture()
        second = {
            "codPedido": 500,
            "codProduto": 9002,
            "descricao": "Produto sintético",
            "quantidade": 1,
            "valor": "5.00",
            "total": "5.00",
        }
        client.get_pedido.return_value["itens"].append(second)
        client.get_cliente_by_cpf.return_value["itens"].append(dict(second))
        _, orders, items = self.resolve_and_persist(contact, client)
        self.assertEqual(len(items), 2)
        self.assertEqual(
            [item["produto_nome"] for item in items],
            ["Produto sintético", "Produto sintético"],
        )
        self.assertEqual(orders[0]["valor_total_compra"], "24.50")
        self.assertEqual(orders[0]["valor_total_faturamento"], "34.49")

    def test_two_contacts_same_cpf_keep_single_official_order(self):
        first, client = self.fixture()
        second = {
            "uuid": "synthetic-u2",
            "fields": {"cpf": "52998224725"},
        }
        rows = [
            normalize_contact(first, "2026-10-05T14:00:00Z"),
            normalize_contact(second, "2026-10-05T14:00:00Z"),
        ]
        responses = {"52998224725": client.get_cliente_by_cpf.return_value}
        orders, items, _ = build_orders(
            [first, second],
            rows_by_uuid={row["contact_uuid"]: row for row in rows},
            farm_client=client,
            sync_time="2026-10-05T14:00:00Z",
            cliente_responses_by_cpf=responses,
        )
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(orders[0]["pedido_id"], "500")


if __name__ == "__main__":
    unittest.main()

# NexoFlow 1.5.3
