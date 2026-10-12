import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

from product_scope import is_animal_product, pharmacy_items
from recompra import PRODUCT_POLICY, apply_review, audit_plan, make_review, propose
from tests.test_recompra import NOW, STRUCTURE, fixture


class ProductScopeTests(unittest.TestCase):
    def test_animal_examples_categories_and_word_boundaries(self):
        names = (
            "BISC CAES PREMIER AD COOKIE FIT FGO 250G",
            "ALIM GATO GRANPLUS FIL FG/ARR 3KG +++",
            "AREIA HIG MAIS CAT 4KG",
            "ALIM CAES PREMIER NATT CL.OBES.PQ 2KG ++",
            "PETISCO P/CAES SPIN PET AMOR/BLUEBER 50G",
            "ALIM CAES FINOTRATO LIFE SEN RPM FG 3k",
            "Ração para cães",
            "NexGard 4kg",
            "Shampoo veterinário",
            "Shampoo VET 100ml",
            "TAPETE HIG PETIX FLOP SLIM 60X55 C/30",
            "TAPETE HIG HUSPET PREMIUM 60X60 C/7",
            "AREIA HIG PIPICAT CLASSIC 12KG",
            "CAPSTAR 11,4MG C/1 CPR",
            "SILMOX CL 150MG",
            "AREIA HIG GREAT PETS BIODEG FINA 2KG",
            "TAPETE HIG CHALESCO CONFORT BAMBOO C/30",
            "VETMAX PLUS VETNIL C/4",
            "DIPIRONA BIOVET GOTA 20ML",
            "HIGIENIZADOR COLLIE P/PATAS 250ML",
            "SUPLEM ERITROS DOG TABS 18G",
            "CAMA BOTIQUE PET ACONCHEG CLASSIC PINK M",
            "CARDALIS 2,5/20 10KG",
            "PHISIODERM VIBRAC SPOT 2ML",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(is_animal_product({"produto_nome": name}))
        self.assertTrue(
            is_animal_product(
                {"produto_nome": "Fórmula X", "categoria": "Medicamentos veterinários"}
            )
        )
        for name in (
            "Paracetamol 500mg",
            "Creme de hidratação",
            "Doxiciclina 100mg",
            "Sabonete Aveeno",
            "Frasco PET 300ml",
            "Shampoo humano",
            "Creme para pés",
            "Soro fisiológico",
            "NEBULIZADOR GTECH DOG AZUL",
            "OLEO SOJA ABC PET 900ML",
            "PETALLA C/30 CPR",
            "PETIVIT BC 240ML",
        ):
            with self.subTest(name=name):
                self.assertFalse(
                    is_animal_product(
                        {
                            "produto_nome": name,
                            "categoria": "Medicamentos e dermocosméticos",
                        }
                    )
                )

    def test_filter_preserves_human_item_values_and_order(self):
        items = [
            {"produto_nome": "Paracetamol", "valor_total": "10"},
            {"produto_nome": "Ração gatos"},
            {"produto_nome": "Creme facial", "valor_total": "20"},
        ]
        filtered = pharmacy_items(items)
        self.assertEqual(filtered, [items[0], items[2]])
        self.assertEqual(len(items), 3)

    def test_pet_only_removes_current_group_without_reentering_admitted_order(self):
        contact, order, items = fixture(24, grouped=True)
        items[0]["produto_nome"] = "BISC CAES PREMIER AD COOKIE FIT FGO 250G"
        saved = {"orders": {"100": {"admitted": True, "pending": True}}}
        before = deepcopy(saved)
        plan = propose(contact, order, items, STRUCTURE, saved, now=NOW)
        self.assertEqual(plan["reason"], "PEDIDO_SOMENTE_PRODUTOS_ANIMAIS")
        self.assertEqual(plan["action"], "remove")
        self.assertEqual(plan["fields"], {})
        self.assertEqual(saved, before)
        contact["groups"] = []
        self.assertEqual(
            propose(contact, order, items, STRUCTURE, saved, now=NOW)["action"], ""
        )

    def test_mixed_order_message_only_has_human_items_and_snapshot_is_complete(self):
        contact, order, items = fixture(24)
        items[0]["produto_nome"] = "Paracetamol 500mg"
        items.append({**items[0], "produto_nome": "AREIA HIG MAIS CAT 4KG"})
        plan = propose(contact, order, items, STRUCTURE, now=NOW)
        self.assertEqual(plan["action"], "add")
        self.assertEqual(plan["fields"]["pedido_produtos"], "Paracetamol 500mg")
        self.assertEqual(plan["fields"]["pedido_data"], order["data_hora"])
        self.assertEqual(len(json.loads(plan["purchase"]["snapshot"])["produtos"]), 2)
        audit_plan(plan)
        forged = deepcopy(plan)
        forged["fields"]["pedido_produtos"] += ", Ração gatos"
        with self.assertRaises(RuntimeError):
            audit_plan(forged)
        forged = deepcopy(plan)
        forged["campaign_products"][0]["categoria"] = "Veterinária"
        with self.assertRaises(RuntimeError):
            audit_plan(forged)

    def test_old_policy_stops_before_connections_or_writes(self):
        contact, order, items = fixture()
        review = make_review(
            [propose(contact, order, items, STRUCTURE, now=NOW)], STRUCTURE, now=NOW
        )
        self.assertEqual(review["policy"], PRODUCT_POLICY)
        review["policy"] = "JANELA_0_A_25_SEM_RECUSA"
        weni = Mock()
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(RuntimeError):
            apply_review(
                review,
                weni,
                Mock(),
                state_path=Path(folder) / "state.json",
                now_fn=lambda: NOW,
            )
        self.assertEqual(weni.mock_calls, [])
