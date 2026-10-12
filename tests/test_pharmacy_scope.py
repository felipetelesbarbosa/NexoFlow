"""Recorte farmacêutico com dados fictícios e gravações Google em memória."""

import json
import re
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from analytics import (
    BASE_COLUMNS,
    BI_CONVERSION_COLUMNS,
    BI_SUMMARY_COLUMNS,
    HISTORY_COLUMNS,
    ORDER_COLUMNS,
    ORDER_ITEM_COLUMNS,
    SALES_METRIC_COLUMNS,
    build_sales_metrics,
    parse_ultimo_pedido_raw,
)
from delivery_tickets import (
    TICKET_COLUMNS,
    apply_delivery_review,
    write_delivery_review,
)
from google_sheets import GoogleSheetsStore
from pharmacy_scope import (
    filter_pharmacy_order,
    plan_pharmacy_scope,
    recalculate_scope_snapshots,
    sanitize_contact_order,
)


def fixture(*, pet_only=False, order_id="700"):
    key = "FARMALIDER:" + order_id
    products = [
        {
            "nome": "Ração para cães 2KG",
            "quantidade": "1",
            "valor_unitario": "30",
            "valor_total": "30",
        }
    ]
    if not pet_only:
        products.insert(
            0,
            {
                "nome": "Protetor solar humano FPS 50",
                "quantidade": "2",
                "valor_unitario": "10",
                "valor_total": "18",
            },
        )
    raw = json.dumps(
        {
            "pedido_id": order_id,
            "data_hora": "2026-10-01T10:00:00-03:00",
            "valor_total_compra": "35" if pet_only else "53",
            "produtos": products,
            "farmalider_frete": "5",
            "farmalider_status_pedido": "2",
            "farmalider_forma_pagamento": "3",
            "status_confirmacao": "CONFIRMADO_API",
        }
    )
    order, items = parse_ultimo_pedido_raw(
        raw, contact_uuid="synthetic-contact", captured_at="2026-10-11T12:00:00Z"
    )
    order["pedido_chave"] = key
    contact = {
        "contact_uuid": "synthetic-contact",
        "nome": "Pessoa sintética",
        "cpf": "52998224725",
        "opt_in_lgpd": "Recusado",
        "ultimo_pedido": raw,
        "pedido_id": order_id,
        "pedido_data": "2026-10-01T10:00:00-03:00",
        "pedido_produtos": ", ".join(product["nome"] for product in products),
        "pedido_quantidade_itens": ", ".join(
            product["quantidade"] for product in products
        ),
        "pedido_valor_produtos": ", ".join(
            product["valor_unitario"] for product in products
        ),
        "pedido_valor": "30" if pet_only else "48",
        "pedido_revisao_pendente": "NOVA_COMPRA_SEM_ID",
    }
    return order, items, contact


class Worksheet:
    def __init__(self, title, headers, records=()):
        self.title = title
        self.values = [list(headers)] + [
            [str(record.get(header) or "") for header in headers] for record in records
        ]
        self.writes = []

    def get_all_values(self):
        return deepcopy(self.values)

    def append_rows(self, rows, **kwargs):
        self.values.extend(deepcopy(rows))
        self.writes.append(("append", deepcopy(rows)))

    def batch_update(self, updates, **kwargs):
        for update in updates:
            number = int(re.search(r"A(\d+):", update["range"])[1])
            self.values[number - 1] = list(update["values"][0])
        self.writes.append(("update", deepcopy(updates)))

    def batch_clear(self, ranges):
        for span in ranges:
            number = int(re.search(r"A(\d+):", span)[1])
            self.values[number - 1] = [""] * len(self.values[0])
        self.writes.append(("clear", list(ranges)))


def store_fixture(orders=(), items=(), contacts=(), history=(), tickets=()):
    store = GoogleSheetsStore.__new__(GoogleSheetsStore)
    store.orders = Worksheet("Pedidos_FarmaLider", ORDER_COLUMNS, orders)
    store.order_items = Worksheet("Itens_Pedidos_FarmaLider", ORDER_ITEM_COLUMNS, items)
    store.base = Worksheet("Base_Contatos", BASE_COLUMNS, contacts)
    store.history = Worksheet("Historico_Alteracoes", HISTORY_COLUMNS, history)
    ticket_sheet = Worksheet("Tickets_Delivery_Weni", TICKET_COLUMNS, tickets)
    store._known_sheets = {ticket_sheet.title: ticket_sheet}
    store._headers_cache = {
        ws.title: ws.values[0][:]
        for ws in (
            store.orders,
            store.order_items,
            store.base,
            store.history,
            ticket_sheet,
        )
    }
    store._read_with_retry = Mock(side_effect=lambda label, operation: operation())
    store._write_with_retry = Mock(side_effect=lambda label, operation: operation())
    return store


class PharmacyScopeTests(unittest.TestCase):
    def test_mixed_order_keeps_discounted_human_value_excludes_freight_and_preserves_status(
        self,
    ):
        order, items, _ = fixture()
        original = deepcopy((order, items))
        filtered, retained = filter_pharmacy_order(order, items)
        self.assertEqual(filtered["valor_total_compra"], "18.00")
        self.assertEqual(filtered["valor_total_faturamento"], "18.00")
        self.assertEqual(filtered["farmalider_frete"], "0.00")
        self.assertEqual(filtered["quantidade_itens"], "2")
        self.assertEqual(filtered["farmalider_status_pedido"], "2")
        self.assertEqual(filtered["farmalider_forma_pagamento"], "3")
        self.assertEqual(retained[0]["valor_unitario"], "10.00")
        self.assertEqual(retained[0]["valor_total"], "18.00")
        self.assertEqual((order, items), original)
        parsed, parsed_items = parse_ultimo_pedido_raw(
            filtered["ultimo_pedido_raw"],
            contact_uuid="synthetic-contact",
            captured_at="",
        )
        self.assertEqual(parsed["status_validacao"], "OK")
        self.assertEqual(len(parsed_items), 1)
        self.assertNotIn("Ração", filtered["ultimo_pedido_raw"])
        metrics = build_sales_metrics([filtered], retained)
        self.assertEqual(
            float(metrics[0][SALES_METRIC_COLUMNS.index("unidades_vendidas")]), 2.0
        )
        self.assertEqual(
            float(metrics[0][SALES_METRIC_COLUMNS.index("faturamento")]), 18.0
        )

    def test_all_animal_order_is_removed(self):
        order, items, _ = fixture(pet_only=True)
        self.assertEqual(filter_pharmacy_order(order, items), (None, []))

    def test_old_mixed_total_and_raw_are_cleaned_when_pet_item_row_was_already_deleted(
        self,
    ):
        order, items, _ = fixture()
        plan = plan_pharmacy_scope([order], items[:1])
        self.assertEqual(plan.orders[0]["valor_total_faturamento"], "18.00")
        self.assertNotIn("Ração", plan.orders[0]["ultimo_pedido_raw"])
        self.assertEqual(len(plan.changed_orders), 1)

    def test_human_order_retains_normal_freight_and_values(self):
        order, items, _ = fixture()
        order["ultimo_pedido_raw"] = ""
        filtered, retained = filter_pharmacy_order(order, items[:1])
        self.assertEqual(filtered, order)
        self.assertEqual(retained, items[:1])
        self.assertEqual(filtered["farmalider_frete"], "5")

    def test_category_classification_preserves_an_unrelated_human_medicine(self):
        order, items, _ = fixture()
        items[0]["produto_nome"] = "Amoxicilina 500mg"
        items[1]["produto_nome"] = "Amoxicilina 250mg"
        items[1]["categoria"] = "Medicamentos veterinários"
        filtered, retained = filter_pharmacy_order(order, items)
        self.assertEqual(
            [item["produto_nome"] for item in retained], ["Amoxicilina 500mg"]
        )
        self.assertEqual(filtered["valor_total_compra"], "18.00")

    def test_malformed_retained_value_cannot_invent_a_sale(self):
        order, items, _ = fixture()
        for invalid in ("não informado", "NaN", "Infinity", "-10"):
            with self.subTest(value=invalid):
                items[0]["valor_total"] = invalid
                with self.assertRaises(ValueError):
                    filter_pharmacy_order(order, items)

    def test_contact_keeps_identity_and_lgpd_but_has_only_human_snapshot(self):
        _, _, contact = fixture()
        cleaned = sanitize_contact_order(contact)
        self.assertEqual(cleaned["cpf"], contact["cpf"])
        self.assertEqual(cleaned["opt_in_lgpd"], "Recusado")
        self.assertEqual(cleaned["pedido_id"], "700")
        self.assertEqual(cleaned["pedido_valor"], "18.00")
        self.assertEqual(cleaned["pedido_quantidade_itens"], "2")
        self.assertNotIn("Ração", json.dumps(cleaned, ensure_ascii=False))
        self.assertEqual(sanitize_contact_order(cleaned), cleaned)

    def test_pet_contact_retains_personal_data_and_pending_review_only(self):
        _, _, contact = fixture(pet_only=True)
        cleaned = sanitize_contact_order(contact)
        self.assertEqual(cleaned["nome"], "Pessoa sintética")
        self.assertEqual(cleaned["opt_in_lgpd"], "Recusado")
        self.assertEqual(cleaned["pedido_revisao_pendente"], "NOVA_COMPRA_SEM_ID")
        self.assertEqual(cleaned["pedido_id"], "")
        self.assertEqual(cleaned["pedido_produtos"], "")
        self.assertEqual(cleaned["ultimo_pedido"], "")

    def test_incomplete_flat_list_is_suppressed_instead_of_guessing_human_prices(self):
        _, _, contact = fixture()
        contact["ultimo_pedido"] = "JSON inválido"
        contact["pedido_valor_produtos"] = ""
        self.assertEqual(sanitize_contact_order(contact)["pedido_produtos"], "")

    def test_history_plan_is_idempotent_and_keeps_old_human_orders(self):
        pet, pet_items, pet_contact = fixture(pet_only=True, order_id="701")
        mixed, mixed_items, mixed_contact = fixture()
        old_human = {"pedido_chave": "FARMALIDER:old", "valor_total_compra": "99"}
        plan = plan_pharmacy_scope(
            [pet, mixed, old_human],
            pet_items + mixed_items,
            [pet_contact, mixed_contact],
        )
        self.assertEqual(plan.removed_order_keys, {"FARMALIDER:701"})
        self.assertEqual(len(plan.removed_item_keys), 2)
        self.assertEqual(plan.orders[-1], old_human)
        repeated = plan_pharmacy_scope(plan.orders, plan.items, plan.contacts)
        self.assertEqual(repeated.counts()["pedidos_pet_removidos"], 0)
        self.assertEqual(repeated.changed_orders, [])
        self.assertEqual(repeated.changed_contacts, [])

    def test_raw_veterinary_category_removes_an_opaque_name_from_item_history(self):
        order, items, _ = fixture()
        payload = json.loads(order["ultimo_pedido_raw"])
        payload["produtos"][1].update(nome="Fórmula XYZ", categoria="Veterinária")
        order["ultimo_pedido_raw"] = json.dumps(payload)
        items[1]["produto_nome"] = "Fórmula XYZ"
        items[1]["categoria"] = ""
        plan = plan_pharmacy_scope([order], items)
        self.assertEqual(plan.removed_item_keys, {items[1]["item_chave"]})
        self.assertEqual(
            [item["produto_nome"] for item in plan.items], [items[0]["produto_nome"]]
        )
        self.assertEqual(plan.orders[0]["valor_total_compra"], "18.00")

    def test_old_snapshots_recompute_only_sales_with_purchase_and_observation_cutoffs(
        self,
    ):
        mixed, items, contact = fixture()
        mixed["capturado_em"] = "2026-10-01T12:00:00Z"
        future = dict(
            mixed,
            pedido_chave="future",
            data="2026-10-02",
            valor_total_compra="500",
            ultimo_pedido_raw="",
        )
        later_observed = dict(
            mixed,
            pedido_chave="late",
            data="2026-09-30",
            capturado_em="2026-10-03T12:00:00Z",
            valor_total_compra="700",
            ultimo_pedido_raw="",
        )
        summary = {
            "data": "2026-10-01",
            "atualizado_em": "2026-10-01T15:00:00Z",
            "contatos_total": 100,
            "opt_in_lgpd": 55,
            "pedidos_total": 3,
            "faturamento_total": 1300,
            "faturamento_frete_total": 20,
            "unidades_vendidas_dia": 7,
        }
        conversions = [
            {
                "chave": "2026-10-01|1",
                "data": "2026-10-01",
                "etapa_ordem": "1",
                "quantidade": 100,
                "atualizado_em": summary["atualizado_em"],
            },
            {
                "chave": "2026-10-01|3",
                "data": "2026-10-01",
                "etapa_ordem": "3",
                "quantidade": 40,
                "atualizado_em": summary["atualizado_em"],
            },
            {
                "chave": "2026-10-01|4",
                "data": "2026-10-01",
                "etapa_ordem": "4",
                "quantidade": 3,
                "atualizado_em": summary["atualizado_em"],
            },
        ]
        summaries, converted = recalculate_scope_snapshots(
            [summary], conversions, [contact], [mixed, future, later_observed], items
        )
        self.assertEqual(summaries[0]["contatos_total"], 100)
        self.assertEqual(summaries[0]["opt_in_lgpd"], 55)
        self.assertEqual(summaries[0]["pedidos_total"], 1)
        self.assertEqual(summaries[0]["faturamento_total"], 18.0)
        self.assertEqual(summaries[0]["faturamento_frete_total"], 0.0)
        self.assertEqual(summaries[0]["unidades_vendidas_dia"], 2.0)
        self.assertEqual(converted[:2], conversions[:2])
        self.assertEqual(converted[2]["quantidade"], 1)
        self.assertEqual(converted[2]["taxa_base_pct"], 1.0)
        self.assertEqual(converted[2]["taxa_etapa_anterior_pct"], 2.5)

    def test_invalid_snapshot_date_and_incomplete_conversion_denominators_are_preserved(
        self,
    ):
        summary = {"data": "desconhecida", "faturamento_total": "30"}
        conversion = {"data": "2026-10-01", "etapa_ordem": "4", "quantidade": "9"}
        self.assertEqual(
            recalculate_scope_snapshots([summary], [conversion], [], [], []),
            ([summary], [conversion]),
        )


class PharmacySheetsTests(unittest.TestCase):
    def test_delivery_apply_filters_pet_and_mixed_orders_through_real_store_methods(
        self,
    ):
        from tests.test_delivery_tickets import (
            DeliveryTicketsTests,
            contact,
            farm,
        )
        from weni_update import REQUIRED_ORDER_FIELDS

        for pet_only in (True, False):
            with self.subTest(pet_only=pet_only):
                client = farm()
                pet_item = {
                    "codPedido": 201,
                    "descricao": "Ração para cães 2KG",
                    "quantidade": 1,
                    "valor": 30,
                    "total": 30,
                }
                api_items = client.get_pedido.return_value["itens"]
                api_items[:] = [pet_item] if pet_only else [api_items[0], pet_item]
                client.get_pedido.return_value["capa"]["frete"] = 5
                plans, delivery = DeliveryTicketsTests().reconcile(client=client)
                delivery["target"] = "analytics"
                store = store_fixture()
                store.bi_summary = Worksheet("BI_Resumo_Diario", BI_SUMMARY_COLUMNS)
                store.bi_conversion = Worksheet("BI_Conversao", BI_CONVERSION_COLUMNS)
                ticket_ws = store._known_sheets["Tickets_Delivery_Weni"]
                store._get_or_create_sheet = Mock(return_value=ticket_ws)
                for name in (
                    "close",
                    "refresh_delivery_bi",
                    "replace_sales_metrics",
                    "replace_bi_orders",
                    "replace_bi_sales",
                    "upsert_bi_summary",
                    "upsert_bi_conversion",
                    "replace_looker_tables",
                    "set_controls",
                ):
                    setattr(store, name, Mock())
                store.get_control = Mock(return_value="")
                weni = Mock()
                weni.list_fields.return_value = [
                    {"key": key} for key in REQUIRED_ORDER_FIELDS
                ]
                weni.get_contact.return_value = contact()
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "review.json"
                    write_delivery_review(plans, delivery, path)
                    apply_delivery_review(
                        path,
                        weni,
                        store_factory=lambda store=store: store,
                        target="analytics",
                    )
                self.assertNotIn(
                    "Ração",
                    json.dumps(
                        store.orders.values
                        + store.order_items.values
                        + store.base.values,
                        ensure_ascii=False,
                    ),
                )
                tickets = store._values_to_records(ticket_ws.values)
                if pet_only:
                    self.assertEqual(len(store.orders.values), 1)
                    self.assertEqual(tickets[0]["pedido_valor"], "")
                    self.assertEqual(
                        tickets[0]["resultado_validacao"], "FORA_ESCOPO_FARMACIA"
                    )
                else:
                    self.assertEqual(len(store.orders.values), 2)
                    records = store.load_order_records()
                    self.assertEqual(records[0]["valor_total_faturamento"], "20.00")
                    self.assertEqual(records[0]["farmalider_frete"], "0.00")
                    self.assertEqual(tickets[0]["pedido_valor"], "20.00")
                weni.update_contact_fields.assert_not_called()

    def test_paired_stale_item_removal_keeps_physical_indices_for_the_next_cleanup(
        self,
    ):
        mixed, mixed_items, _ = fixture()
        pet, pet_items, _ = fixture(pet_only=True, order_id="701")
        store = store_fixture([mixed, pet], mixed_items + pet_items)
        orders, items = store.upsert_pharmacy_orders([mixed], mixed_items)
        self.assertEqual(len(items.final_records), 3)
        self.assertEqual(items.final_records[1]["item_chave"], "")
        store.reconcile_pharmacy_scope(
            base_records=[],
            order_records=orders.final_records,
            item_records=items.final_records,
            include_history=False,
        )
        self.assertTrue(all(not cell for cell in store.order_items.values[3]))
        self.assertTrue(
            store.order_items.values[1][ORDER_ITEM_COLUMNS.index("item_chave")]
        )

    def test_ticket_gate_clears_pet_value_and_uses_human_value_before_writing(self):
        mixed, mixed_items, _ = fixture()
        pet, pet_items, _ = fixture(pet_only=True, order_id="701")
        store = store_fixture()
        store.upsert_pharmacy_orders([mixed, pet], mixed_items + pet_items)
        ws = store._known_sheets["Tickets_Delivery_Weni"]
        store._get_or_create_sheet = Mock(return_value=ws)
        result = store.upsert_delivery_tickets(
            [
                {
                    "ticket_uuid": "pet",
                    "pedido_chave": pet["pedido_chave"],
                    "pedido_valor": "30",
                },
                {
                    "ticket_uuid": "mixed",
                    "pedido_chave": mixed["pedido_chave"],
                    "pedido_valor": "48",
                },
            ]
        )
        self.assertEqual(result.final_records[0]["pedido_valor"], "")
        self.assertEqual(
            result.final_records[0]["resultado_validacao"], "FORA_ESCOPO_FARMACIA"
        )
        self.assertEqual(result.final_records[1]["pedido_valor"], "18.00")

    def test_old_bi_cleanup_reuses_reads_and_keeps_original_contact_numbers(self):
        mixed, items, contact = fixture()
        mixed["capturado_em"] = "2026-10-01T12:00:00Z"
        store = store_fixture()
        store.bi_summary = Worksheet(
            "BI_Resumo_Diario",
            BI_SUMMARY_COLUMNS,
            [
                {
                    "data": "2026-10-01",
                    "atualizado_em": "2026-10-01T15:00:00Z",
                    "contatos_total": 100,
                    "faturamento_total": 53,
                }
            ],
        )
        store.bi_conversion = Worksheet("BI_Conversao", BI_CONVERSION_COLUMNS)
        counts = store.resanitize_pharmacy_bi_snapshots([contact], [mixed], items)
        self.assertEqual(counts["resumos_saneados"], 1)
        self.assertEqual(store._read_with_retry.call_count, 2)
        record = store._values_to_records(store.bi_summary.values)[0]
        self.assertEqual(record["contatos_total"], "100")
        self.assertEqual(record["faturamento_total"], 18.0)

    def test_paired_ingestion_never_writes_animal_products_or_pet_totals(self):
        mixed, mixed_items, _ = fixture()
        pet, pet_items, _ = fixture(pet_only=True, order_id="701")
        store = store_fixture()
        orders, items = store.upsert_pharmacy_orders(
            [mixed, pet], mixed_items + pet_items
        )
        self.assertEqual(orders.inserted, 1)
        self.assertEqual(items.inserted, 1)
        self.assertEqual(orders.final_records[0]["valor_total_faturamento"], "18.00")
        self.assertNotIn(
            "Ração",
            json.dumps(
                store.orders.values + store.order_items.values, ensure_ascii=False
            ),
        )

    def test_paired_ingestion_removes_a_previously_stored_pet_order_and_items(self):
        pet, items, _ = fixture(pet_only=True)
        store = store_fixture([pet], items)
        orders, retained_items = store.upsert_pharmacy_orders([pet], items)
        self.assertTrue(all(not row["pedido_chave"] for row in orders.final_records))
        self.assertTrue(
            all(not row["item_chave"] for row in retained_items.final_records)
        )
        self.assertEqual(store.orders.writes[0][0], "clear")
        self.assertEqual(store.order_items.writes[0][0], "clear")

    def test_direct_contact_upsert_and_history_append_sanitize_before_writing(self):
        _, _, contact = fixture()
        store = store_fixture()
        result = store.upsert_contacts_detailed([contact])
        self.assertEqual(result.final_records[0]["pedido_valor"], "18.00")
        store._append_history_batch = Mock()
        store.append_history([contact], set())
        history_rows = store._append_history_batch.call_args.args[0]
        self.assertNotIn("Ração", json.dumps(history_rows, ensure_ascii=False))

    def test_direct_order_raw_gate_sanitizes_mixed_and_skips_pet(self):
        mixed, _, _ = fixture()
        pet, _, _ = fixture(pet_only=True, order_id="701")
        store = store_fixture()
        result = store.upsert_orders_detailed([mixed, pet])
        self.assertEqual(result.inserted, 1)
        self.assertEqual(result.final_records[0]["valor_total_compra"], "18.00")

    def test_direct_item_gate_removes_stored_pet_and_keeps_the_human_position(self):
        _, items, _ = fixture()
        store = store_fixture(items=items)
        result = store.upsert_order_items_detailed(items)
        self.assertEqual(result.removed, 1)
        self.assertEqual(result.final_records[0]["item_chave"], items[0]["item_chave"])
        self.assertEqual(result.final_records[0]["produto_ordem"], "1")

    def test_complete_cleanup_sanitizes_history_tickets_and_contact_without_deleting_contact(
        self,
    ):
        pet, pet_items, pet_contact = fixture(pet_only=True, order_id="701")
        mixed, mixed_items, mixed_contact = fixture()
        mixed_contact["contact_uuid"] = "other-contact"
        tickets = [
            {
                "ticket_uuid": "pet-ticket",
                "contact_uuid": "synthetic-contact",
                "pedido_chave": pet["pedido_chave"],
                "pedido_valor": "30",
            },
            {
                "ticket_uuid": "mixed-ticket",
                "contact_uuid": "other-contact",
                "pedido_chave": mixed["pedido_chave"],
                "pedido_valor": "48",
            },
        ]
        store = store_fixture(
            [pet, mixed],
            pet_items + mixed_items,
            [pet_contact, mixed_contact],
            [pet_contact, mixed_contact],
            tickets,
        )
        plan = store.reconcile_pharmacy_scope()
        self.assertEqual(plan.counts()["pedidos_pet_removidos"], 1)
        self.assertEqual(plan.history_changed, 2)
        self.assertEqual(plan.tickets_changed, 2)
        base = store.load_base_records()
        self.assertEqual(len(base), 2)
        self.assertEqual(base[0]["cpf"], "52998224725")
        self.assertEqual(base[0]["pedido_id"], "")
        ticket_records = store._values_to_records(
            store._known_sheets["Tickets_Delivery_Weni"].values
        )
        self.assertEqual(
            ticket_records[0]["resultado_validacao"], "FORA_ESCOPO_FARMACIA"
        )
        self.assertEqual(ticket_records[1]["pedido_valor"], "18.00")
        self.assertNotIn("Ração", json.dumps(store.history.values, ensure_ascii=False))
        writes = store._write_with_retry.call_count
        repeated = store.reconcile_pharmacy_scope()
        self.assertEqual(repeated.changed_orders, [])
        self.assertEqual(store._write_with_retry.call_count, writes)

    def test_clear_preserves_physical_row_numbers_after_blank_rows(self):
        pet, items, _ = fixture(pet_only=True)
        store = store_fixture([{}, pet], [{}, *items])
        store.reconcile_pharmacy_scope(include_history=False)
        self.assertEqual(len(store.orders.writes[0][1]), 1)
        self.assertRegex(store.orders.writes[0][1][0], r"^A3:[A-Z]+3$")
        self.assertEqual(store.orders.values[1], [""] * len(ORDER_COLUMNS))


if __name__ == "__main__":
    unittest.main()
