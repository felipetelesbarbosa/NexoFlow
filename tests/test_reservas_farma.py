import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import UUID

import reservas_farma
from recompra import apply_review, load_state, make_review, propose
from run_noturno import reservas_da_execucao
from tests.test_recompra import NOW, STRUCTURE, fixture

UID = str(UUID(int=1))


class ReservasFarmaTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.manifest = self.root / "reservas.json"
        self.ativar([UID])
        self.enterContext(patch.object(reservas_farma, "MANIFESTO", self.manifest))

    def ativar(self, ids):
        self.manifest.write_text(
            json.dumps(
                {"segmento": "FARMA", "adiar_exclusoes": True, "contatos_recompra": ids}
            ),
            encoding="utf-8",
        )

    def test_noturno_exige_quantidade_e_fixa_a_lista_para_os_filhos(self):
        with self.assertRaises(RuntimeError), reservas_da_execucao(24):
            self.fail("iniciou com quantidade incorreta")
        with reservas_da_execucao(1):
            self.assertEqual(reservas_farma.carregar("PET").contatos, frozenset())
            self.manifest.unlink()
            with self.assertRaisesRegex(RuntimeError, "mudou"):
                reservas_farma.carregar("FARMA")
        with self.assertRaises(RuntimeError):
            reservas_farma.conferir(1)

    def test_arquivo_invalido_bloqueia(self):
        for ids in ([UID, UID], ["invalido"], [None]):
            self.ativar(ids)
            with self.assertRaises(RuntimeError):
                reservas_farma.carregar("FARMA")

    def test_inclusao_e_troca_preservam_membro_e_pedido_em_duas_revisoes(self):
        for membro in (False, True):
            path = self.root / f"estado-{membro}.json"
            weni = Mock()
            c, o, itens = fixture(24, grouped=membro)
            c["uuid"] = UID
            for _ in range(2):
                state = load_state(path)
                plan = propose(c, o, itens, STRUCTURE, now=NOW)
                self.assertEqual(plan["action"], "replace" if membro else "add")
                plan["_incremental"] = {"source": "sintetico", "policy": "teste"}
                review = make_review([plan], STRUCTURE, now=NOW, state=state)
                report = self.root / "recibo.json"
                with patch("recompra.inspect_structure", return_value=STRUCTURE):
                    result = apply_review(
                        review,
                        weni,
                        Mock(),
                        state_path=path,
                        now_fn=lambda: NOW,
                        audit_path=self.root / "audit.jsonl",
                        pending_report_path=report,
                    )
                self.assertEqual(result["reservados"], 1)
                self.assertEqual(
                    json.loads(report.read_text())["pendencias"][0]["status"],
                    "RESERVADO",
                )
                state = load_state(path)
                self.assertNotIn(UID, state["contacts"])
                self.assertTrue(state["incremental"]["contacts"][UID]["retry"])
            weni.get_contact.assert_not_called()
            weni.update_contact_fields.assert_not_called()
            weni.contact_group_action.assert_not_called()
            self.manifest.unlink()
            with self.assertRaisesRegex(RuntimeError, "mudaram"):
                apply_review(review, weni, Mock(), state_path=path, now_fn=lambda: NOW)
            self.ativar([UID])
