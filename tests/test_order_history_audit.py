import io
import json
import sqlite3
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import patch

from order_history import HistoryError, HistoryQuery, normalize_order
from order_history_store import HistoryStore, collect_windows, history_audit
from run_order_history import interactive, print_progress, print_summary, run
from tests.test_order_history import NOW, Source, order


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.store = HistoryStore(self.db, "PET")
        self.q = HistoryQuery("PET", "2026-11-01", "2026-11-06", 500)

    def test_scopes_pending_and_no_network_on_second_run(self):
        self.store.upsert(
            normalize_order(order(90, day="2025-01-01"), "PET", NOW),
            now=NOW,
            mode="historica",
        )
        source = Source([order(), order(2, status=3), order(3)])
        source.rows[2]["itens"][0]["desconto"] = 5
        first = collect_windows(source, self.store, self.q, now=NOW)
        self.assertEqual(first["execution"]["novos"], 3)
        self.assertEqual(first["execution"]["pendentes_recebidos"], 1)
        self.assertEqual(first["audit"]["periodo"]["pedidos_validos"], 1)
        self.assertEqual(first["audit"]["acumulado"]["pedidos_validos"], 2)
        self.assertEqual(first["audit"]["acumulado"]["faturamento_centavos"], 16000)
        self.assertEqual(
            first["audit"]["pendencias"][0]["motivo"],
            "DESCONTO_OU_TOTAL_NAO_CONCILIADO",
        )
        again = collect_windows(source, self.store, self.q, now=NOW)
        self.assertEqual(len(source.calls), 1)
        self.assertEqual(again["execution"]["novos"], 0)
        self.assertEqual(again["execution"]["registros_recebidos"], 0)
        self.assertEqual(again["pendencias"], 1)
        with redirect_stdout(io.StringIO()) as output:
            print_summary(first)
        self.assertIn("R$ 160,00", output.getvalue())
        self.assertIn("PERÍODO SOLICITADO", output.getvalue())
        self.assertIn("ORIGENS DOS FATOS ARMAZENADOS", output.getvalue())
        for source, count in first["audit"]["origens"].items():
            self.assertIn(f"{source}: {count} pedido(s)", output.getvalue())
        self.assertIn(
            "origem do fato=" + first["audit"]["pendencias"][0]["origem"],
            output.getvalue(),
        )

    def test_shared_boundary_and_existing_updated(self):
        class Boundary:
            def get_pedidos_history(_, q, page):
                rows = [order(1, day="2026-02-01")]
                return Source(rows).get_pedidos_history(q, page)

        q = HistoryQuery("PET", "2026-01-01", "2026-03-01")
        result = collect_windows(Boundary(), self.store, q, now=NOW)
        self.assertEqual(result["execution"]["registros_recebidos"], 2)
        self.assertEqual(result["execution"]["ids_unicos"], 1)
        self.assertEqual(result["execution"]["repetidos_entre_janelas"], 1)
        self.assertEqual(result["pedidos_validos"], 1)
        changed = collect_windows(
            Source([order(1, status=3, day="2026-02-01")]),
            self.store,
            HistoryQuery("PET", "2026-02-01", "2026-02-01"),
            now=NOW,
            mode="reconciliacao",
        )
        self.assertEqual(changed["execution"]["atualizados"], 1)
        self.assertEqual(changed["execution"]["ja_existentes"], 1)

    def test_volume_31285_against_larger_accumulation(self):
        record = normalize_order(order(90000, day="2025-01-01"), "PET", NOW)
        self.db.executemany(
            "INSERT INTO history_orders VALUES(?,?,?,?,?,?)",
            [
                ("PET", str(i), "10", json.dumps(dict(record, id=str(i))), NOW, NOW)
                for i in range(90000, 102521)
            ],
        )
        self.db.commit()
        counts = [3455, 3595, 3867, 3325, 3264, 2896, 2857, 2932, 2571, 2523]

        class Volume:
            windows = {}

            def get_pedidos_history(inner, q, page):
                index = inner.windows.setdefault(q.key, len(inner.windows))
                total = counts[index]
                rows = [
                    order(index * 5000 + i + 1, day=q.start)
                    for i in range((page - 1) * 500, min(page * 500, total))
                ]
                return dict(
                    pedidos=rows,
                    pagina=page,
                    limite=500,
                    totalRegistros=total,
                    totalPaginas=(total + 499) // 500,
                )

        result = collect_windows(
            Volume(),
            self.store,
            HistoryQuery("PET", "2026-01-01", "2026-11-06"),
            now=NOW,
        )
        self.assertEqual(result["execution"]["registros_recebidos"], 31285)
        self.assertEqual(result["execution"]["novos"], 31285)
        self.assertEqual(result["pedidos_validos"], 43806)
        self.assertEqual(result["pages_this_run"], 67)
        self.assertEqual(result["incomplete_windows"], 0)

    def test_terminal_cancellation_validation_defaults_and_pending_code(self):
        for values in (
            ["exit"],
            ["2026-01-01", "", "sair"],
            ["2026-01-01", "", "500", "0"],
        ):
            with (
                patch("builtins.input", side_effect=values),
                patch("run_order_history.run") as runner,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(interactive(), 130)
                runner.assert_not_called()
        with (
            patch(
                "builtins.input",
                side_effect=["bad", "bad", "2026-01-01", "", "bad", "", ""],
            ),
            patch("run_order_history.run", return_value=3) as runner,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(interactive(), 3)
            self.assertIn("500", runner.call_args.args[0])
        for error in (EOFError, KeyboardInterrupt):
            with (
                patch("builtins.input", side_effect=error),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(interactive(), 130)
        with self.assertRaisesRegex(HistoryError, "MAXIMO_PAGINAS"):
            run(["--max-paginas", "0"])
        with redirect_stdout(io.StringIO()) as output:
            print_progress(
                dict(
                    next_page=7,
                    pages=6,
                    received=2523,
                    total=2523,
                    status="extraida",
                    window=10,
                    windows=10,
                )
            )
        self.assertNotIn("próxima página", output.getvalue())
        self.assertIn("10/10", output.getvalue())

    def test_reordered_items_preserve_positions_and_do_not_reopen_old_closing(self):
        from copy import deepcopy

        payload = order(88, day="2026-01-01")
        second = deepcopy(payload["itens"][0])
        second.update(id="second", codProduto=9)
        payload["itens"].append(second)
        first = normalize_order(payload, "PET", NOW)
        self.store.upsert(first, now=NOW, mode="historica")
        payload["itens"].reverse()
        incoming = normalize_order(payload, "PET", NOW)
        self.assertEqual(
            self.store.upsert(incoming, now=NOW, mode="historica"), "existente"
        )
        self.assertEqual(list(self.store.records())[0], first)
        self.assertEqual(self.store.totals()["pendencias"], 0)
        self.assertEqual(
            self.db.execute("SELECT count(*) FROM history_revisions").fetchone()[0], 0
        )
        payload["itens"][0]["total"] = 90
        payload["itens"][0]["valor"] = 90
        changed = normalize_order(payload, "PET", NOW)
        self.assertEqual(
            self.store.upsert(changed, now=NOW, mode="historica"), "preservado"
        )
        self.assertEqual(self.store.totals()["pendencias"], 1)

    def test_empty_and_multiple_orders_same_owner(self):
        self.assertEqual(history_audit(self.store)["acumulado"]["pedidos_validos"], 0)
        for oid in (1, 2):
            self.store.upsert(
                normalize_order(order(oid), "PET", NOW), now=NOW, mode="historica"
            )
        result = history_audit(self.store)["acumulado"]
        self.assertEqual(result["clientes_com_compras_validas"], 1)
        self.assertEqual(result["pedidos_sem_vinculo"], 2)

    def test_readonly_legacy_database_and_pending_exit_code(self):
        import hashlib
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite"
            with closing(sqlite3.connect(path)) as db:
                store = HistoryStore(db, "PET")
                bad = order()
                del bad["itens"]
                store.upsert(
                    normalize_order(bad, "PET", NOW), now=NOW, mode="historica"
                )
                db.commit()
                db.execute("DROP TABLE history_run_receipts")
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            with (
                patch("runtime_profile.segment", return_value="PET"),
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(run(["--auditar-banco", str(path)]), 3)
            self.assertIn("ITENS_AUSENTES", output.getvalue())
            self.assertEqual(before, hashlib.sha256(path.read_bytes()).hexdigest())

    def test_link_counts_orders_separately_from_distinct_buyers(self):
        from unittest.mock import Mock

        for oid in (1, 2):
            self.store.upsert(
                normalize_order(order(oid), "PET", NOW), now=NOW, mode="historica"
            )
        self.db.commit()
        with patch(
            "order_history.IdentityIndex.match",
            return_value=("contact-sintetico", "CONFIRMADO"),
        ):
            counts = self.store.link(Mock(segment="PET", by_id={"10": {}}), [])
        self.assertEqual(counts["vinculados"], 2)
        totals = history_audit(self.store)["acumulado"]
        self.assertEqual(totals["clientes_com_vinculo"], 1)
        self.assertEqual(totals["contatos_weni_distintos"], 1)

    def test_parent_menu_propagates_partial_and_failure(self):
        from nexo_cli import _menu

        for expected, kwargs in (
            (3, dict(return_value=3)),
            (1, dict(side_effect=HistoryError("FALHA_LEITURA_API"))),
        ):
            with (
                patch("run_order_history.interactive", **kwargs),
                patch("builtins.input", side_effect=["10", "", "0"]),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(_menu(), expected)
