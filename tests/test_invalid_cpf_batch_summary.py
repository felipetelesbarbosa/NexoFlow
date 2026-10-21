import unittest
from unittest.mock import Mock, patch

from weni_update import (
    ContactUpdatePlan,
    UpdateStats,
    _apply_purchase_candidate,
    _invalid_cpf_summary,
    _InvalidCpfBatch,
    _plan_digest,
    _record_invalid_cpf_result,
)


class InvalidCpfBatchSummaryTests(unittest.TestCase):
    def test_501_contact_checks_emit_one_full_and_one_partial_batch(self):
        batch = _InvalidCpfBatch()
        with patch("weni_update.logging.info") as log:
            for i in range(501):
                batch.record(
                    ContactUpdatePlan(
                        contact_uuid=f"synthetic-{i}",
                        order_resolution_status="CPF_IDENTIDADE_DIVERGENTE",
                    )
                )
            batch.flush()
            batch.flush()
        lines = [call.args[0] % call.args[1:] for call in log.call_args_list]
        self.assertEqual(len(lines), 2)
        self.assertIn("lote 1", lines[0])
        self.assertIn("contatos avaliados=500", lines[0])
        self.assertIn("divergência=500", lines[0])
        self.assertIn("lote 2", lines[1])
        self.assertIn("contatos avaliados=1", lines[1])
        self.assertIn("divergência=1", lines[1])
        self.assertTrue(all("synthetic-" not in line for line in lines))

    def test_outcomes_count_unchanged_cancelled_and_blocked_contacts_separately(self):
        stats = UpdateStats()
        plans = [
            ContactUpdatePlan("unchanged", order_validated=True),
            ContactUpdatePlan(
                "cancelled", order_validated=True, purchase_confirmation="CANCELADO_API"
            ),
            ContactUpdatePlan("older", order_found=True),
        ] + [
            ContactUpdatePlan(str(i), order_resolution_status=status)
            for i, status in enumerate(
                [
                    "CPF_IDENTIDADE_DIVERGENTE",
                    "CPF_IDENTIDADE_AMBIGUA",
                    "CPF_IDENTIDADE_INSUFICIENTE",
                    "CPF_NAO_ENCONTRADO",
                    "SEM_PEDIDO_VALIDADO",
                    "ERRO_API",
                    "PEDIDO_DATA_INVALIDA_API",
                ]
            )
        ]
        for plan in plans:
            _record_invalid_cpf_result(stats, plan)
        self.assertEqual(stats.invalid_cpf_checked, 10)
        self.assertEqual(sum(stats.invalid_cpf_outcomes.values()), 10)
        self.assertEqual(stats.invalid_cpf_orders_found, 3)
        self.assertEqual(stats.invalid_cpf_orders_validated, 2)
        text = _invalid_cpf_summary(stats)
        for label in [
            "divergência",
            "identidade ambígua",
            "dados insuficientes",
            "cliente não encontrado",
            "sem pedido validado",
            "falha API",
            "outros impedimentos",
        ]:
            self.assertIn(label + "=1", text)

    def test_identity_failure_remains_blocked_without_warning_per_contact(self):
        import logging

        for status in [
            "CPF_IDENTIDADE_DIVERGENTE",
            "CPF_IDENTIDADE_AMBIGUA",
            "CPF_IDENTIDADE_INSUFICIENTE",
        ]:
            with self.subTest(status=status):
                plan = ContactUpdatePlan("synthetic")
                with (
                    patch(
                        "weni_update.resolve_contact_order",
                        return_value=(
                            {"status_confirmacao": status},
                            [],
                        ),
                    ),
                    patch("weni_update.logging.getLogger") as root,
                    patch("weni_update.logging.log") as log,
                ):
                    root.return_value.isEnabledFor.return_value = True
                    accepted = _apply_purchase_candidate(
                        plan,
                        {"uuid": "synthetic", "fields": {"cpf": "0"}},
                        farm_client=Mock(),
                        captured_at="2026-10-08T10:00:00Z",
                    )
                self.assertFalse(accepted)
                self.assertFalse(plan.order_validated)
                self.assertFalse(plan.order_found)
                self.assertEqual(plan.order_resolution_status, status)
                self.assertEqual(plan.fields, {})
                self.assertEqual(log.call_args.args[0], logging.DEBUG)
                self.assertNotIn("synthetic", str(log.call_args))

    def test_order_found_is_not_lost_when_existing_order_date_is_newer(self):
        plan = ContactUpdatePlan("synthetic")
        order = {
            "status_confirmacao": "CONFIRMADO_API",
            "status_validacao": "OK",
            "pedido_id": "123",
            "data_hora": "2026-06-01T10:00:00-03:00",
            "valor_total_compra": "10",
            "farmalider_status_pedido": "2",
        }
        items = [
            {
                "produto_nome": "Produto sintético",
                "quantidade": "1",
                "valor_unitario": "10",
            }
        ]
        with patch("weni_update.resolve_contact_order", return_value=(order, items)):
            accepted = _apply_purchase_candidate(
                plan,
                {
                    "uuid": "synthetic",
                    "fields": {"cpf": "0", "pedido_data": "02/06/26 10:00:00"},
                },
                farm_client=Mock(),
                captured_at="2026-10-08T10:00:00Z",
            )
        self.assertFalse(accepted)
        self.assertTrue(plan.order_found)
        self.assertFalse(plan.order_validated)
        self.assertEqual(plan.fields, {})
        stats = UpdateStats()
        _record_invalid_cpf_result(stats, plan)
        self.assertEqual(stats.invalid_cpf_orders_found, 1)
        self.assertEqual(stats.invalid_cpf_orders_validated, 0)

    def test_valid_cpf_identity_ambiguity_is_consolidated_without_warning_per_contact(
        self,
    ):
        import logging

        plan = ContactUpdatePlan("synthetic")
        with (
            patch(
                "weni_update.resolve_contact_order",
                return_value=(
                    {"status_confirmacao": "CPF_IDENTIDADE_AMBIGUA"},
                    [],
                ),
            ),
            patch("weni_update.logging.getLogger") as root,
            patch("weni_update.logging.log") as log,
        ):
            root.return_value.isEnabledFor.return_value = True
            _apply_purchase_candidate(
                plan,
                {"uuid": "synthetic", "fields": {"cpf": "52998224725"}},
                farm_client=Mock(),
                captured_at="2026-10-08T10:00:00Z",
            )
        self.assertEqual(log.call_args.args[0], logging.DEBUG)
        self.assertFalse(plan.order_validated)

    def test_quiet_checkup_does_not_force_identity_warning(self):
        plan = ContactUpdatePlan("synthetic")
        with (
            patch(
                "weni_update.resolve_contact_order",
                return_value=(
                    {"status_confirmacao": "CPF_IDENTIDADE_AMBIGUA"},
                    [],
                ),
            ),
            patch("weni_update.logging.getLogger") as root,
            patch("weni_update.logging.log") as log,
        ):
            root.return_value.isEnabledFor.return_value = False
            _apply_purchase_candidate(
                plan,
                {"uuid": "synthetic", "fields": {"cpf": "52998224725"}},
                farm_client=Mock(),
                captured_at="2026-10-08T10:00:00Z",
            )
        log.assert_not_called()
        self.assertFalse(plan.order_validated)

    def test_diagnostic_metadata_does_not_change_frozen_plan_digest(self):
        plan = ContactUpdatePlan("synthetic")
        original = _plan_digest([plan])
        plan.order_found = True
        plan.order_resolution_status = "CONFIRMADO_API"
        self.assertEqual(_plan_digest([plan]), original)

    def test_interruption_flush_counts_only_completed_contacts_once(self):
        batch = _InvalidCpfBatch()
        with patch("weni_update.logging.info") as log:
            batch.record(ContactUpdatePlan("synthetic", order_validated=True))
            batch.flush(interrupted=True)
            batch.flush(interrupted=True)
        self.assertEqual(log.call_count, 1)
        line = log.call_args.args[0] % log.call_args.args[1:]
        self.assertIn("interrompido (contatos concluídos)", line)
        self.assertIn("contatos avaliados=1", line)
