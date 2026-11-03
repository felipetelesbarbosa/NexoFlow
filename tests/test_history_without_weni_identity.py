"""Vendas oficiais não dependem de haver um único cadastro/conversa na Weni."""

import os
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from customer_observations import acknowledge, history_rows, record_directory
from farmalider_customers import CustomerDirectory
from tests.test_farmalider_customers import CPF, customer_snapshot

CAPTURED = "2026-11-03T12:00:00-03:00"


def snapshot(oid=8, owner=17, cpf=CPF, segment="FARMA"):
    row = customer_snapshot(cpf=cpf)
    row["cliente"]["id"] = owner
    for address in row["cliente"].get("enderecos", []):
        address["clienteId"] = owner
    row["ultimoPedido"].update(id=oid, codCliente=owner, segmento=segment)
    for item in row["itens"]:
        item["codPedido"] = oid
    return row


def contact(uid, cpf=CPF, *, order="", phone="", name="Pessoa Sintética"):
    return {
        "uuid": uid,
        "name": name,
        "fields": {"cpf": cpf, "pedido_id": order},
        "urns": ["whatsapp:" + phone] if phone else [],
    }


class HistoryWithoutWeniIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="history_identity_regression_")
        self.addCleanup(temp.cleanup)
        patcher = patch("customer_observations.DB_ROOT", Path(temp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        profile = patch.dict(os.environ, NEXOFLOW_PERFIL="FARMA")
        profile.start()
        self.addCleanup(profile.stop)

    def observe(self, rows, segment="FARMA"):
        # Simular coletas sucessivas: cada cliente só tem um último pedido por coleta.
        for row in rows:
            record_directory(CustomerDirectory([row], segment=segment), CAPTURED)

    def read(self, contacts, existing=(), *, existing_items=None):
        return history_rows(
            contacts,
            list(existing),
            captured_at=CAPTURED,
            existing_items=existing_items,
        )

    def test_six_orders_three_duplicate_cpfs_are_imported_without_invented_links(self):
        cpfs = [CPF, "16899535009", "11144477735"]
        contacts, snapshots = [], []
        for i, cpf in enumerate(cpfs):
            contacts.extend([contact(f"{i}-a", cpf), contact(f"{i}-b", cpf)])
            snapshots.extend(
                [snapshot(100 + i * 2, 17 + i, cpf), snapshot(101 + i * 2, 17 + i, cpf)]
            )
        self.observe(snapshots)
        orders, items, receipts = self.read(contacts)
        self.assertEqual(len(orders), 6)
        self.assertEqual(
            {o["pedido_id"] for o in orders}, {str(100 + i) for i in range(6)}
        )
        self.assertTrue(all(not o["contact_uuid"] for o in orders))
        self.assertTrue(
            all(o["status_confirmacao"] == "CONFIRMADO_API" for o in orders)
        )
        self.assertEqual(len(items), 6)
        self.assertEqual(len(receipts), 6)
        self.assertTrue(
            all(o["origem_pedido"] == "FARMALIDER_HISTORICO_OBSERVADO" for o in orders)
        )

    def test_malformed_weni_cpf_does_not_discard_official_order_or_repair_contact(self):
        row = snapshot()
        person = contact("bad", cpf="CPF: " + CPF)
        original = deepcopy(person)
        self.observe([row])
        orders, _, receipts = self.read([person])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["contact_uuid"], "")
        self.assertEqual(orders[0]["cpf_normalizado"], CPF)
        self.assertEqual(person, original)
        self.assertEqual(len(receipts), 1)

    def test_unique_matching_order_reference_selects_contact(self):
        self.observe([snapshot()])
        orders, _, _ = self.read(
            [contact("first", order="8"), contact("second", order="9")]
        )
        self.assertEqual(orders[0]["contact_uuid"], "first")

    def test_unique_exact_api_phone_breaks_duplicate_cpf_tie(self):
        row = snapshot()
        self.observe([row])
        phone = str(row["cliente"]["celular"])
        orders, _, _ = self.read(
            [contact("first"), contact("second", phone="+55" + phone)]
        )
        self.assertEqual(orders[0]["contact_uuid"], "second")

    def test_missing_phone_does_not_use_name_only_to_choose_duplicate(self):
        self.observe([snapshot()])
        orders, _, _ = self.read(
            [contact("same-name"), contact("different-name", name="Outra pessoa")]
        )
        self.assertEqual(orders[0]["contact_uuid"], "")

    def test_invalid_mathematical_cpf_without_independent_identity_is_not_self_confirmed(
        self,
    ):
        row = snapshot(cpf="12345678901")
        self.observe([row])
        self.assertEqual(self.read([]), ([], [], []))
        self.assertEqual(
            self.read([contact("unknown", cpf="12345678901", name="")]), ([], [], [])
        )

    def test_invalid_mathematical_cpf_with_real_weni_identity_remains_supported(self):
        row = snapshot(cpf="12345678901")
        self.observe([row])
        orders, _, _ = self.read([contact("matched", cpf="12345678901")])
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]["contact_uuid"], "matched")
        self.assertTrue(orders[0]["origem_pedido"].endswith("_IDENTIDADE_VALIDADA"))

    def test_receipts_are_idempotent_and_orphan_can_be_linked_after_later_discovery(
        self,
    ):
        self.observe([snapshot()])
        orders, _, receipts = self.read([contact("a"), contact("b")])
        self.assertEqual(len(orders), 1)
        acknowledge(receipts)
        self.assertEqual(self.read([contact("a"), contact("b")], orders), ([], [], []))
        relinked, _, receipts = self.read(
            [contact("a", order="8"), contact("b")], orders
        )
        self.assertEqual(relinked[0]["contact_uuid"], "a")
        acknowledge(receipts)
        self.assertEqual(
            self.read([contact("a", order="8"), contact("b")], relinked), ([], [], [])
        )

    def test_existing_different_owner_cannot_be_hijacked(self):
        self.observe([snapshot()])
        other = {
            "pedido_id": "8",
            "pedido_chave": "FARMALIDER:8",
            "farmalider_cliente_id": "999",
            "farmalider_cod_cliente": "999",
            "valor_total_compra": "42",
        }
        before = deepcopy(other)
        self.assertEqual(self.read([], [other]), ([], [], []))
        self.assertEqual(other, before)

    def test_both_segments_allow_financial_history_without_weni_contact(self):
        for segment in ("FARMA", "PET"):
            with (
                self.subTest(segment=segment),
                patch.dict(os.environ, NEXOFLOW_PERFIL=segment),
            ):
                self.observe([snapshot(segment=segment)], segment)
                orders, _, _ = self.read([])
                self.assertEqual(len(orders), 1)
                self.assertEqual(orders[0]["contact_uuid"], "")
