"""Frete do cabeçalho é fonte financeira; divergência isolada é aviso."""

import sqlite3
import unittest
from contextlib import closing
from copy import deepcopy

from order_history import normalize_order
from order_history_store import HistoryStore, history_audit
from tests.test_order_history import NOW, order


def with_freight(header, item):
    row = order(day="2026-01-01")
    row["capa"]["frete"] = header
    row["itens"].append(
        dict(
            row["itens"][0],
            id="freight",
            codProduto=0,
            descricao="",
            valor=item,
            total=item,
        )
    )
    return row


class FreightWarningTests(unittest.TestCase):
    def test_freight_disagreement_does_not_exclude_sale_or_double_count(self):
        for segment in ("FARMA", "PET"):
            for header, item, expected in ((9.99, 0, 8999), (0, 9.99, 8000)):
                row = with_freight(header, item)
                row["capa"]["segmento"] = segment
                record = normalize_order(row, segment, NOW)
                self.assertEqual(record["state"], "valido")
                self.assertEqual(record["revenue_cents"], expected)
                self.assertEqual(record["products_cents"], 8000)
                self.assertEqual(record["warnings"][0]["reason"], "FRETE_DIVERGENTE")
                with closing(sqlite3.connect(":memory:")) as db:
                    store = HistoryStore(db, segment)
                    store.upsert(record, now=NOW, mode="historica")
                    self.assertEqual(store.totals()["pendencias"], 0)
                    self.assertEqual(store.totals()["faturamento_centavos"], expected)
                    self.assertEqual(
                        history_audit(store)["acumulado"]["avisos_frete"], 1
                    )

    def test_shipping_item_metadata_does_not_reopen_old_closing(self):
        row = with_freight(9.99, 9.99)
        before = normalize_order(row, "PET", NOW)
        row["itens"][1].update(valor=0, total=0)
        after = normalize_order(row, "PET", NOW)
        with closing(sqlite3.connect(":memory:")) as db:
            store = HistoryStore(db, "PET")
            store.upsert(before, now=NOW, mode="historica")
            self.assertEqual(
                store.upsert(after, now=NOW, mode="historica"), "existente"
            )
            self.assertEqual(store.totals()["pendencias"], 0)
            self.assertEqual(store.totals()["faturamento_centavos"], 8999)

    def test_other_financial_errors_and_cancellation_remain_blocking(self):
        good = with_freight(9.99, 0)
        for mutate, state in (
            (lambda r: r["capa"].update(status=3), "cancelado"),
            (lambda r: r["itens"][0].update(desconto=1), "pendente"),
            (lambda r: r["capa"].update(valorTotal=80), "pendente"),
        ):
            row = deepcopy(good)
            mutate(row)
            self.assertEqual(normalize_order(row, "PET", NOW)["state"], state)

    def test_zero_code_with_description_remains_product(self):
        row = with_freight(0, 9.99)
        row["itens"][1]["descricao"] = "Produto com descrição"
        record = normalize_order(row, "PET", NOW)
        self.assertEqual(record["state"], "valido")
        self.assertEqual(record["products_cents"], 8999)
        self.assertNotIn("warnings", record)
