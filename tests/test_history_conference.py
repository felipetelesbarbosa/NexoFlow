import json
import sqlite3
import unittest
from copy import deepcopy

from history_conference import compare, from_published, summarize
from order_history import normalize_order
from tests.test_order_history import NOW, order


class ConferenceTests(unittest.TestCase):
    def test_item_conference_work_is_bounded_by_matching_orders_and_items(self):
        """O ORDER BY não pode induzir uma varredura de todos os itens por pedido."""
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE incoming(t TEXT,k TEXT,v TEXT,PRIMARY KEY(t,k))")
        count = 1200
        for number in range(count):
            key = f"FARMA:{number:06d}"
            row = dict(
                pedido_id=str(number),
                segmento="FARMA",
                cliente_id="cliente",
                data="2026-11-01",
                estado="valido",
                produtos="5",
                frete="0.5",
                faturamento="5.5",
                vigente="Sim",
            )
            db.execute(
                "INSERT INTO incoming VALUES(?,?,?)",
                ("Historico_Pedidos", key, json.dumps(row)),
            )
            for item in range(5):
                db.execute(
                    "INSERT INTO incoming VALUES(?,?,?)",
                    (
                        "Historico_Itens",
                        f"{key}:{item}",
                        json.dumps(
                            dict(
                                pedido_id=str(number),
                                segmento="FARMA",
                                quantidade=1,
                                frete="Não",
                                vigente="Sim",
                            )
                        ),
                    ),
                )
        db.commit()
        ticks = 0

        def budget():
            nonlocal ticks
            ticks += 1
            return int(ticks > 1000)

        # Limite de instruções, sem depender da velocidade da máquina ou do relógio.
        db.set_progress_handler(budget, 1000)
        try:
            report = summarize(from_published(db, "incoming"), "FARMA")
        finally:
            db.set_progress_handler(None, 0)
        total = report["recortes"][-1]
        self.assertEqual(total["pedidos"], count)
        self.assertEqual(total["itens_linhas_validas"], count * 5)
        self.assertEqual(total["faturamento_centavos"], count * 550)
        self.assertEqual(total["unidades_validas"], str(count * 5))

    def test_shared_boundary_receipts_do_not_duplicate_monthly_financials(self):
        import sqlite3

        from history_conference import receipts
        from order_history import HistoryQuery
        from order_history_store import HistoryStore, collect_windows
        from tests.test_order_history import Source

        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        history = HistoryStore(db, "FARMA")
        row = order(1, day="2026-11-01", segment="FARMA")
        collect_windows(
            Source([row]),
            history,
            HistoryQuery("FARMA", "2026-10-01", "2026-11-07", 500),
            now=NOW,
        )
        raw = receipts(history)
        self.assertEqual(raw["execucoes"][0]["recebimentos_brutos"], 2)
        self.assertEqual(raw["execucoes"][0]["ids_unicos"], 1)
        result = summarize(history.records(), "FARMA")
        self.assertEqual(result["recortes"][-1]["pedidos"], 1)
        self.assertEqual(result["recortes"][-1]["faturamento_centavos"], 8000)

    def test_sheet_summary_and_private_conference_use_belem_for_naive_midnight(self):
        import json

        from order_history_sheets import tables
        from order_history_store import HistoryStore
        from tests.test_history_publication import fixture

        db, _ = fixture(1)
        self.addCleanup(db.close)
        history = HistoryStore(db, "FARMA")
        row = next(history.records())
        row["date"] = "2026-11-01T00:30:00"
        db.execute("UPDATE history_orders SET record=?", (json.dumps(row),))
        data = tables(history)
        months = [r for r in data["BI_Historico_Resumo"] if r["tipo_recorte"] == "MES"]
        self.assertEqual([r["competencia"] for r in months], ["2026-11"])
        report = summarize(history.records(), "FARMA")
        self.assertEqual(report["recortes"][0]["recorte"], "2026-11")

    def test_distinct_customer_total_duplicate_order_and_missing_date(self):
        rows = [
            normalize_order(order(1, day="2026-10-05", segment="FARMA"), "FARMA", NOW),
            normalize_order(order(2, day="2026-11-05", segment="FARMA"), "FARMA", NOW),
            normalize_order(
                order(3, day="2026-11-05", status=3, segment="FARMA"), "FARMA", NOW
            ),
        ]
        pending = deepcopy(rows[0])
        pending.update(
            id="4",
            date="",
            state="pendente",
            items=[],
            products_cents=0,
            freight_cents=0,
            revenue_cents=0,
        )
        rows.extend([pending, deepcopy(rows[0])])
        report = summarize(iter(rows), "FARMA")
        total = report["recortes"][-1]
        self.assertEqual(total["pedidos"], 4)
        self.assertEqual(total["validos"], 2)
        self.assertEqual(total["clientes_com_compra_valida"], 1)
        self.assertEqual(total["faturamento_centavos"], 16000)
        self.assertEqual(
            next(r for r in report["recortes"] if r["recorte"] == "SEM_EMISSAO")[
                "pendentes"
            ],
            1,
        )
        self.assertIsNone(report["recebimentos_brutos_por_mes"])
        self.assertEqual(compare(report, deepcopy(report))["estado"], "conferido")
        changed = deepcopy(report)
        changed["recortes"][-1]["faturamento_centavos"] += 1
        diff = compare(report, changed)
        self.assertEqual(diff["diferencas"][0]["diferenca"], "1")
        self.assertFalse(
            any(k in total for k in ("cpf", "cliente_id", "pedido_id", "contato_weni"))
        )
