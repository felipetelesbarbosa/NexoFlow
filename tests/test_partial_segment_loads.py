"""Regressões de cargas parciais e guardas PET com APIs sintéticas."""

import json
import os
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from farmalider_client import FarmaliderLookupError
from main import FarmaliderSettings, _completion_controls, validate_contacts
from recompra import apply_review, inspect_structure, load_state, make_review, propose
from tests.test_recompra import NOW, fixture
from tests.test_recompra_prevention import weni_fixture


class PartialSegmentLoadsTests(unittest.TestCase):
    def test_analytics_real_pipeline_saves_valid_order_and_retries_incomplete_contact(
        self,
    ):
        import main
        from tests.test_farmalider_customers import CPF, customer_snapshot

        for segment in ("FARMA", "PET"):
            with self.subTest(segment=segment), ExitStack() as stack:
                contacts = [
                    {"uuid": "healthy", "name": "Synthetic", "fields": {"cpf": CPF}},
                    {
                        "uuid": "pending",
                        "name": "Synthetic",
                        "fields": {"cpf": "16899535009"},
                    },
                ]
                farm, sheets, weni = Mock(), Mock(), Mock()
                snapshot = customer_snapshot()
                snapshot["ultimoPedido"]["segmento"] = segment
                incomplete = [True]

                def query(cpf, snapshot=snapshot, incomplete=incomplete):
                    if cpf == CPF:
                        return deepcopy(snapshot)
                    if incomplete[0]:
                        raise FarmaliderLookupError("ERRO_RESPOSTA_CLIENTE_API")
                    return {
                        "cliente": {"id": 999, "cpf": int(cpf), "nome": "Sintético"},
                        "ultimoPedido": None,
                        "itens": [],
                    }

                farm.get_cliente_by_cpf.side_effect = query
                farm.get_pedido.return_value = {
                    "capa": snapshot["ultimoPedido"],
                    "itens": snapshot["itens"],
                }
                farm.metrics_snapshot.return_value = {
                    "total_requests": 2,
                    "retries": 0,
                    "rate_limits": 0,
                    "server_errors": 0,
                    "max_response_ms": 1,
                    "effective_delay_ms": 0,
                }
                weni.list_contacts.return_value = contacts
                sheets.load_base_snapshot.return_value = ([], [], set())
                sheets.load_order_records.return_value = []
                sheets.load_order_item_records.return_value = []
                controls = {
                    "ultima_sincronizacao_sucesso_utc": "2026-10-01T12:00:00+00:00"
                }
                sheets.get_control.side_effect = lambda key, controls=controls: (
                    controls.get(key, "")
                )
                sheets.set_controls.side_effect = controls.update
                sheets.request_stats.return_value = {
                    "reads": 1,
                    "writes": 1,
                    "total": 2,
                }

                def upsert(rows, **_):
                    return SimpleNamespace(
                        inserted=len(rows),
                        updated=0,
                        unchanged=0,
                        final_records=deepcopy(rows),
                        changed_records=deepcopy(rows),
                    )

                sheets.upsert_contacts_detailed.side_effect = upsert
                sheets.upsert_pharmacy_orders.side_effect = lambda orders, items: (
                    upsert(orders),
                    upsert(items),
                )
                sheets.reconcile_pharmacy_scope.side_effect = lambda **kw: (
                    SimpleNamespace(
                        contacts=kw["base_records"],
                        orders=kw["order_records"],
                        items=kw["item_records"],
                    )
                )
                stack.enter_context(
                    patch.dict(
                        os.environ,
                        {
                            "FORCE_FULL_SYNC": "",
                            "FULL_SYNC_QUARTER": "",
                            "NEXOFLOW_BI_INICIO": "",
                            "NEXOFLOW_BI_FIM": "",
                        },
                    )
                )
                for target, value in (
                    ("main.configure_logging", None),
                    ("main.validate_configuration", None),
                    ("main.open_farmalider_client", farm),
                    ("main.GoogleSheetsStore", sheets),
                    ("main.WeniClient", weni),
                ):
                    stack.enter_context(patch(target, return_value=value))
                stack.enter_context(
                    patch("runtime_profile.segment", return_value=segment)
                )
                stack.enter_context(
                    patch("main.FARMALIDER_BATCH_ERROR_WARN_MIN_ERRORS", 1)
                )
                stack.enter_context(patch("main.FARMALIDER_BATCH_ERROR_WARN_RATE", 0.2))
                stack.enter_context(patch("customer_observations.acknowledge"))
                self.assertEqual(main.main(), 3)
                self.assertEqual(controls["ultima_execucao_status"], "parcial")
                self.assertEqual(
                    controls["ultima_sincronizacao_sucesso_utc"],
                    "2026-10-01T12:00:00+00:00",
                )
                written = sheets.upsert_pharmacy_orders.call_args.args[0]
                self.assertTrue(
                    any(
                        r.get("status_confirmacao") == "CONFIRMADO_API"
                        and r.get("pedido_id") == "8"
                        for r in written
                    )
                )
                self.assertFalse(
                    any(
                        r.get("status_confirmacao") == "CONFIRMADO_API"
                        and r.get("contact_uuid") == "pending"
                        for r in written
                    )
                )
                self.assertTrue(sheets.replace_looker_tables.called)
                incomplete[0] = False
                self.assertEqual(main.main(), 0)
                self.assertEqual(controls["ultima_execucao_status"], "sucesso")
                self.assertEqual(controls["ultima_execucao_clientes_sem_pedido"], "1")
                self.assertNotEqual(
                    controls["ultima_sincronizacao_sucesso_utc"],
                    "2026-10-01T12:00:00+00:00",
                )

    def test_many_unconfirmed_segments_do_not_discard_healthy_contacts_or_advance_cursor(
        self,
    ):
        farm = Mock()
        farm.metrics_snapshot.return_value = {
            "total_requests": 200,
            "retries": 0,
            "rate_limits": 0,
            "server_errors": 0,
            "max_response_ms": 1,
            "effective_delay_ms": 0,
        }

        def query(cpf):
            if int(cpf) < 1132:
                raise FarmaliderLookupError("ERRO_RESPOSTA_CLIENTE_API")
            return None

        farm.get_cliente_by_cpf.side_effect = query
        rows = [
            {"contact_uuid": f"synthetic-{i}", "cpf": f"{1000 + i:011d}"}
            for i in range(200)
        ]
        statuses = {}
        with (
            patch("main.is_valid_cpf", return_value=True),
            patch("main.FARMALIDER_BATCH_SIZE", 100),
            patch("main.FARMALIDER_MAX_WORKERS", 1),
        ):
            stats = validate_contacts(
                rows,
                farm_client=farm,
                farm_settings=FarmaliderSettings(True, "SYNTHETIC", False),
                sync_time=NOW.isoformat(),
                cliente_lookup_status_by_cpf=statuses,
            )
        self.assertEqual(farm.get_cliente_by_cpf.call_count, 200)
        self.assertEqual(stats.api_errors, 132)
        self.assertEqual(stats.not_found, 68)
        self.assertEqual(len(statuses), 200)
        self.assertEqual(
            rows[0]["farmalider_cliente_status"], "ERRO_RESPOSTA_CLIENTE_API"
        )
        self.assertEqual(rows[-1]["farmalider_cliente_status"], "CPF_NAO_ENCONTRADO")
        self.assertEqual(
            _completion_controls(NOW, api_errors=stats.api_errors),
            ("parcial", {"ultima_execucao_status": "parcial"}),
        )

    def test_pet_updates_physical_purchase_field_without_alias_conflict(self):
        for grouped in (False, True):
            with self.subTest(grouped=grouped), TemporaryDirectory() as folder:
                contact, order, items = fixture(24, grouped=grouped)
                contact["fields"]["compra_recente"] = "2026-08-01T12:00:00-03:00"
                contact["fields"]["opt_in_marketing"] = "Sim"
                if grouped:
                    contact["fields"]["pedido_data"] = contact["fields"][
                        "compra_recente"
                    ]
                client, live = weni_fixture("PET", [contact])
                structure = inspect_structure(client, segment="PET")
                path, audit = Path(folder) / "state.json", Path(folder) / "audit.jsonl"
                with patch("runtime_profile.segment", return_value="PET"):
                    plan = propose(contact, order, items, structure, now=NOW)
                    self.assertIn("compra_recente", plan["fields"])
                    review = make_review(
                        [plan], structure, now=NOW, state=load_state(path)
                    )
                    with patch("recompra.resolve_latest", return_value=(order, items)):
                        result = apply_review(
                            review,
                            client,
                            Mock(),
                            state_path=path,
                            audit_path=audit,
                            now_fn=lambda: NOW,
                        )
                self.assertEqual(result, {"aplicados": 1})
                self.assertEqual(
                    live[contact["uuid"]]["fields"]["compra_recente"],
                    plan["fields"]["compra_recente"],
                )
                self.assertTrue(
                    load_state(path)["contacts"][contact["uuid"]]["orders"]["100"][
                        "admitted"
                    ]
                )
                self.assertEqual(
                    json.loads(audit.read_text().splitlines()[-1])["status"], "APLICADO"
                )

    def test_pet_physical_legacy_changes_remain_detectable(self):
        from recompra import guard

        contact, _, _ = fixture(24)
        original = deepcopy(contact)
        with patch("runtime_profile.segment", return_value="PET"):
            for key in (
                "ultima_compra",
                "marketing_opt_in",
                "opt_in_marketing",
                "compra_recente",
            ):
                changed = deepcopy(original)
                changed["fields"][key] = "changed"
                with self.subTest(key=key):
                    self.assertNotEqual(guard(original), guard(changed))
