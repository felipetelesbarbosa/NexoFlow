"""Histórico incremental sobre o SQLite temporário do backend PostgreSQL."""

import json
import unittest
from contextlib import closing
from unittest.mock import Mock

from ds_backend.cache import connect
from ds_backend.contract import record_key
from order_history import HistoryError, HistoryQuery
from order_history_store import HistoryStore
from tests.test_order_history import NOW, Source, order


class PostgresCacheChangesTests(unittest.TestCase):
    def setUp(self):
        self.store = Mock(readonly=False, _cache={})
        self.store.records.return_value = []

    def test_pagina_incremental_corrige_pedido_existente_uma_vez(self):
        with closing(connect(self.store)) as db:
            history = HistoryStore(db, "FARMA")
            query = HistoryQuery("FARMA", "2026-11-01", "2026-11-06", 100)
            for amount in (80, 85, 85):
                history.begin(query, restart=True)
                source = Source([order(segment="FARMA", amount=amount)])
                page = source.get_pedidos_history(query, 1)
                self.store._send.reset_mock()
                state = history.commit_page(query, 1, page, now=NOW, mode="incremental")
                self.assertEqual((state["received"], state["status"]), (1, "extraida"))
                changes = [
                    c.args
                    for c in self.store._send.call_args_list
                    if c.args[0] == "Cache_history_orders"
                ]
                self.assertEqual(len(changes), 1)
                _, rows, removed = changes[0]
                self.assertEqual((len(rows), removed), (1, []))
                self.assertEqual(json.loads(rows[0]["record"])["id"], "1")
                self.assertEqual(history.totals()["faturamento_centavos"], amount * 100)
            history.begin(query, restart=True)
            invalid = Source([order(segment="FARMA", amount=90)] * 2)
            self.store._send.reset_mock()
            with self.assertRaisesRegex(HistoryError, "PAGINA_COM_IDS_REPETIDOS"):
                history.commit_page(
                    query,
                    1,
                    invalid.get_pedidos_history(query, 1),
                    now=NOW,
                    mode="incremental",
                )
            valid = Source([order(segment="FARMA", amount=90)])
            with self.assertRaisesRegex(RuntimeError, "interrupção simulada"):
                history.commit_page(
                    query,
                    1,
                    valid.get_pedidos_history(query, 1),
                    now=NOW,
                    mode="incremental",
                    interrupt=Mock(side_effect=RuntimeError("interrupção simulada")),
                )
            self.store._send.assert_not_called()
            self.assertEqual(history.state(query)["next_page"], 1)
            self.assertEqual(history.totals()["faturamento_centavos"], 8500)

    def test_falha_ao_carregar_cache_permite_repetir_com_o_mesmo_destino(self):
        self.store.records.side_effect = TimeoutError("falha de leitura simulada")
        with self.assertRaises(TimeoutError):
            connect(self.store)
        self.store.records.side_effect = None
        self.store.records.return_value = []
        with closing(connect(self.store)) as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM history_orders").fetchone(), (0,)
            )
        self.store._send.assert_not_called()

    def test_troca_de_chave_e_ultima_operacao_por_linha(self):
        with closing(connect(self.store)) as db:
            with db:
                db.execute("INSERT INTO creations(id,status) VALUES('old','before')")
            self.store._send.reset_mock()
            with db:
                db.execute("UPDATE creations SET id='new' WHERE id='old'")
                db.execute("DELETE FROM creations WHERE id='new'")
                db.execute("INSERT INTO creations(id,status) VALUES('new','after')")
            self.store._send.assert_called_once_with(
                "Cache_creations",
                [{"id": "new", "status": "after", "uuid": ""}],
                [record_key("Cache_creations", {"id": "old"})],
            )
