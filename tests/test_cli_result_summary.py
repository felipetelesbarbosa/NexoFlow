"""Resultados parciais preservam contagens confirmadas e causas independentes."""

import contextlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import MagicMock, patch

import run_noturno
import run_recompra
import run_update_weni
from weni_update import UpdateStats


class CliResultSummaryTests(unittest.TestCase):
    def test_confirmed_fields_remain_counted_when_admission_is_blocked(self):
        self._assert_partial_writes("before_admission")

    def test_compensated_inclusion_counts_writes_without_claiming_valid_admission(self):
        self._assert_partial_writes("after_admission")

    def test_compensated_replacement_counts_both_confirmed_removals(self):
        self._assert_partial_writes("after_admission", replace=True)

    def _assert_partial_writes(self, failure_stage, *, replace=False):
        from recompra import apply_review, inspect_structure, make_review, propose
        from tests.test_recompra import NOW, fixture
        from tests.test_recompra_prevention import weni_fixture

        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), tempfile.TemporaryDirectory() as folder:
                contact, order, items = fixture(24, grouped=replace)
                client, live = weni_fixture(segment, [contact])
                structure = inspect_structure(client, segment=segment)
                plan = propose(contact, order, items, structure, now=NOW)
                original_update = client.update_contact_fields.side_effect
                original_group = client.contact_group_action.side_effect

                def update(uid, fields, original_update=original_update, live=live):
                    original_update(uid, fields)
                    if failure_stage == "before_admission":
                        live[uid]["name"] = "Identificação alterada após revisão"

                def group(
                    uid, *, action, group, original_group=original_group, live=live
                ):
                    original_group(uid, action=action, group=group)
                    if failure_stage == "after_admission" and action == "add":
                        live[uid]["fields"]["pedido_produtos"] = ""

                client.update_contact_fields.side_effect = update
                client.contact_group_action.side_effect = group
                root = Path(folder)
                report_path = root / "application.json"
                with patch("recompra.resolve_latest", return_value=(order, items)):
                    result = apply_review(
                        make_review([plan], structure, now=NOW),
                        client,
                        MagicMock(),
                        state_path=root / "state.json",
                        audit_path=root / "audit.jsonl",
                        pending_report_path=report_path,
                        now_fn=lambda: NOW,
                    )
                report = json.loads(report_path.read_text())
                writes = report["escritas_confirmadas"]
                self.assertEqual(result, {"conflitos": 1})
                self.assertEqual(writes.get("contatos_com_escrita_weni", 0), 1)
                self.assertEqual(writes.get("campos_enviados", 0), len(plan["fields"]))
                self.assertEqual(writes.get("inclusoes_confirmadas", 0), 0)
                expected_reversals = int(failure_stage == "after_admission")
                expected_removals = expected_reversals + int(replace)
                self.assertEqual(
                    writes.get("remocoes_confirmadas", 0), expected_removals
                )
                self.assertEqual(
                    writes.get("inclusoes_revertidas", 0), expected_reversals
                )
                client.update_contact_fields.assert_called_once()
                self.assertEqual(
                    client.contact_group_action.call_count,
                    expected_removals + expected_reversals,
                )
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    run_recompra.print_application_summary(result, report)
                self.assertIn("Contatos com escrita na Weni: 1", output.getvalue())
                if expected_removals:
                    self.assertIn(
                        "Inclusões revertidas preventivamente: 1", output.getvalue()
                    )

    def test_recompra_report_counts_only_confirmed_remote_writes(self):
        from recompra import apply_review, make_review, propose
        from tests.test_recompra import GROUP, NOW, STRUCTURE, fixture

        contact, order, items = fixture(24)
        # Fields are already correct; the only POST needed is the group admission.
        contact["fields"].update(
            propose(contact, order, items, STRUCTURE, now=NOW)["fields"]
        )
        existing = deepcopy(contact)
        existing["uuid"] = "already-grouped"
        existing["groups"] = [{"uuid": STRUCTURE["group_uuid"], "name": GROUP}]
        contacts = {c["uuid"]: c for c in (contact, existing)}
        plans = [
            propose(c, order, items, STRUCTURE, now=NOW) for c in contacts.values()
        ]
        client = MagicMock()
        client.get_contact.side_effect = lambda *, uuid: deepcopy(contacts[uuid])
        client.contact_group_action.side_effect = lambda uid, **kw: contacts[uid][
            "groups"
        ].append({"uuid": kw["group"], "name": GROUP})
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("recompra.inspect_structure", return_value=STRUCTURE),
            patch("recompra._resolve_checked_contact", return_value=(order, items)),
        ):
            root = Path(folder)
            report_path = root / "application.json"
            result = apply_review(
                make_review(plans, STRUCTURE, now=NOW),
                client,
                MagicMock(),
                state_path=root / "state.json",
                audit_path=root / "audit.jsonl",
                pending_report_path=report_path,
                now_fn=lambda: NOW,
            )
            report = json.loads(report_path.read_text())
        self.assertEqual(result["aplicados"], 2)
        self.assertEqual(client.contact_group_action.call_count, 1)
        self.assertEqual(report["escritas_confirmadas"]["contatos_com_escrita_weni"], 1)
        self.assertEqual(report["escritas_confirmadas"]["inclusoes_confirmadas"], 1)
        self.assertEqual(report["escritas_confirmadas"]["campos_enviados"], 0)

    def test_recompra_does_not_describe_local_confirmations_as_weni_posts(self):
        result = {
            "aplicados": 68,
            "estado_local": 1,
            "sem_mudanca": 1096,
            "consultas_pendentes": 852,
        }
        report = {
            "escritas_confirmadas": {
                "contatos_com_escrita_weni": 28,
                "campos_enviados": 0,
                "inclusoes_confirmadas": 28,
                "remocoes_confirmadas": 0,
            },
            "pendencias_por_motivo": {"CONSULTA_PENDENTE": 852},
        }
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            run_recompra.print_application_summary(result, report)
        text = output.getvalue()
        self.assertIn("Contatos com escrita na Weni: 28", text)
        self.assertIn("Inclusões confirmadas no grupo: 28", text)
        self.assertIn("Confirmações sem escrita na Weni: 40", text)
        self.assertIn("Atualizações somente no estado local: 1", text)
        self.assertIn("Consultas para revalidar: 852", text)
        self.assertIn("não representam POSTs nem mensagens enviadas", text)
        self.assertNotIn("68 contatos incluídos", text)

    def test_weni_actual_cli_distinguishes_new_from_total_confirmed_contacts(self):
        stats = UpdateStats(contacts_updated=7, contacts_created=2, orders_api_failed=1)
        dedup = {"proposed": 0, "deleted": 0, "pending": 0, "skipped": 0}
        output = io.StringIO()
        with (
            patch("sys.argv", ["app/run_update_weni.py", "--apply"]),
            patch.object(run_update_weni, "configure_proxy", return_value=MagicMock()),
            patch("logging_config.configure_logging"),
            patch("weni_dedup.run_with_dedup", return_value=(stats, dedup)),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(run_update_weni.main(), 0)
        text = output.getvalue()
        self.assertIn("Contatos com plano de gravação concluído, total: 7", text)
        self.assertIn("Novos contatos criados nesta carga: 2", text)
        self.assertIn("Contatos existentes atualizados: 5", text)
        self.assertIn("FarmaLíder: consultas para revalidar=1", text)
        self.assertIn("--- CONFIRMADO NESTA CARGA ---", text)
        self.assertIn("--- PARA REVALIDAR NA PRÓXIMA CARGA ---", text)

    def test_weni_does_not_report_zero_writes_when_only_complete_plans_are_counted(
        self,
    ):
        stats = UpdateStats(contacts_failed=1)
        dedup = {"proposed": 0, "deleted": 0, "pending": 0, "skipped": 0}
        output = io.StringIO()
        with (
            patch("sys.argv", ["app/run_update_weni.py", "--apply"]),
            patch.object(run_update_weni, "configure_proxy", return_value=MagicMock()),
            patch("logging_config.configure_logging"),
            patch("weni_dedup.run_with_dedup", return_value=(stats, dedup)),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(run_update_weni.main(), 0)
        text = output.getvalue()
        self.assertIn("Contatos com plano de gravação concluído, total: 0", text)
        self.assertIn("Contatos pendentes podem ter escritas parciais", text)
        self.assertNotIn("Contatos gravados na Weni, total: 0", text)

    def test_local_confirmations_do_not_subtract_writes_of_conflicted_plans(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            run_recompra.print_application_summary(
                {"aplicados": 1, "conflitos": 1},
                {
                    "escritas_confirmadas": {
                        "contatos_com_escrita_weni": 1,
                        "confirmacoes_sem_escrita_weni": 1,
                    }
                },
            )
        self.assertIn("Confirmações sem escrita na Weni: 1", output.getvalue())

    def test_final_analytics_partial_completes_nightly_flow_without_claiming_failure(
        self,
    ):
        calls = []

        def runner(arguments, **kwargs):
            calls.append(arguments)
            return 3 if len(calls) == 11 else 0

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(run_noturno.execute(root, runner=runner), 3)
            report = json.loads(
                next((root / "logs/noturno").glob("*/resultado.json")).read_text()
            )
        self.assertTrue(report["fluxo_completo"])
        self.assertIn("fluxo concluído com pendências", output.getvalue())
        self.assertIn("Etapas concluídas: 11", output.getvalue())
        self.assertIn("Etapas com pendências: 1", output.getvalue())


if __name__ == "__main__":
    unittest.main()
