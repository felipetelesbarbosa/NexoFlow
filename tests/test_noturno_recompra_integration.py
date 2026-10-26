"""CLI real da Recompra dentro do Noturno; somente serviços externos simulados."""

import contextlib
import io
import json
import tempfile
import unittest
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import run_noturno
from config import WENI_CONTACT_ACTIONS_API_URL, WENI_CONTACTS_API_URL
from farmalider_client import FarmaliderError
from recompra import load_state
from run_recompra import main as recompra_cli
from tests.test_pedido_resolution import cliente_payload, pedido_payload
from tests.test_recompra import NOW, STRUCTURE, fixture
from tests.test_recompra_group_api_contract import FakeResponse, FakeWeniTransport
from weni_client import WeniClient


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)


class SimulatedFarmalider:
    def __init__(self, scenario):
        self.scenario = scenario

    def get_cliente_by_cpf(self, cpf):
        payload = cliente_payload()
        payload["ultimoPedido"]["id"] = 100
        payload["itens"] = []  # Exige a consulta real pelo ID do pedido.
        if cpf != "52998224725":
            payload["cliente"].update(id=199, cpf=cpf)
            payload["ultimoPedido"].update(id=456, codCliente=199)
        elif self.scenario["changed"]:
            payload["ultimoPedido"]["id"] = 789
        return payload

    def get_pedido(self, order_id):
        if str(order_id) == "456":
            raise FarmaliderError("Falha sintética de itens")
        payload = pedido_payload()
        payload["capa"]["id"] = 100
        payload["itens"][0]["codPedido"] = 100
        if str(order_id) == "789":
            payload["capa"]["id"] = 789
            payload["capa"]["emissao"] = "2026-10-07T10:30:00"
            payload["itens"][0]["codPedido"] = 789
        return payload

    def close(self):
        pass


class NoturnoRecompraIntegrationTests(unittest.TestCase):
    def run_scenario(self, mode, *, full=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            good, _, _ = fixture(24)
            bad = deepcopy(good)
            bad["uuid"] = "synthetic-broken"
            bad["urns"] = ["tel:+5591988888888"]
            bad["fields"].update(cpf="11144477735", pedido_status="3")
            transports = {
                good["uuid"]: FakeWeniTransport(
                    good, make_add_visible=mode != "uncertain_post"
                ),
                bad["uuid"]: FakeWeniTransport(bad),
            }
            if mode == "success":
                transports.pop(bad["uuid"])
            for transport in transports.values():
                transport.state_path = root / "logs/recompra_state.json"
            scenario = {"changed": False}
            calls = []

            def request(method, url, *, params=None, json=None, **kwargs):
                if (
                    method == "GET"
                    and url == WENI_CONTACTS_API_URL
                    and not (params or {}).get("uuid")
                ):
                    return FakeResponse(
                        {
                            "results": [t.contact for t in transports.values()],
                            "next": None,
                        }
                    )
                uid = (params or {}).get("uuid")
                if url == WENI_CONTACT_ACTIONS_API_URL:
                    uid = json["contacts"][0]
                return transports[uid].request(
                    method, url, params=params, json=json, **kwargs
                )

            def client_factory(token, **kwargs):
                client = WeniClient(token, **kwargs)
                patches.enter_context(
                    patch.object(client.session, "request", side_effect=request)
                )
                return client

            def runner(arguments, **kwargs):
                calls.append(arguments)
                if arguments[0] != "app/run_recompra.py":
                    return 0  # Integrações Weni/Analytics são auditadas separadamente.
                cli_args = arguments[1:]
                if mode == "legacy_strict" and "--dry-run" in arguments:
                    cli_args = [*cli_args, "--require-complete"]
                code = recompra_cli(cli_args)
                if "--dry-run" in arguments:
                    if mode == "source_changed":
                        scenario["changed"] = True
                    elif mode == "tampered_review":
                        path = Path(arguments[arguments.index("--review-out") + 1])
                        payload = json.loads(path.read_text(encoding="utf-8"))
                        payload["review"]["day"] = "2000-01-01"
                        path.write_text(json.dumps(payload), encoding="utf-8")
                return code

            with (
                contextlib.ExitStack() as patches,
                contextlib.chdir(root),
                contextlib.redirect_stdout(io.StringIO()),
                patch("proxy_config.configure_proxy"),
                patch("logging_config.configure_logging"),
                patch("weni_client.WeniClient", side_effect=client_factory),
                patch(
                    "weni_update._open_farmalider",
                    side_effect=lambda: SimulatedFarmalider(scenario),
                ),
                patch("recompra.inspect_structure", return_value=STRUCTURE),
                patch("recompra.datetime", FixedDateTime),
                patch(
                    "recompra.WENI_UPDATE_STATE_FILE",
                    root / "logs/weni_update_state.json",
                ),
                patch("recompra.sleep"),
            ):
                code = run_noturno.execute(root, runner=runner, full=full)
                result = json.loads(
                    next((root / "logs/noturno").glob("*/resultado.json")).read_text(
                        encoding="utf-8"
                    )
                )
                reports = list(
                    (root / "logs/noturno").glob("*/privado/*_aplicacao.json")
                )
                if mode in {"success", "partial_queries", "source_changed"}:
                    self.assertEqual(len(reports), 1)
                    application = json.loads(reports[0].read_text(encoding="utf-8"))
                    self.assertTrue(application["aplicacao_concluida"])
                    self.assertEqual(bool(application["pendencias"]), code == 3)
                else:
                    self.assertEqual(reports, [])
                state = load_state(root / "logs/recompra_state.json")
            posts = [
                call
                for transport in transports.values()
                for call in transport.calls
                if call[0] == "POST"
            ]
            audit = root / "logs/recompra_audit.jsonl"
            events = (
                [
                    json.loads(line)
                    for line in audit.read_text(encoding="utf-8").splitlines()
                ]
                if audit.exists()
                else []
            )
            return code, result, state, calls, posts, events

    def test_successful_cli_flow_completes_and_confirms_admission(self):
        for full in (False, True):
            with self.subTest(full=full):
                code, result, state, calls, posts, events = self.run_scenario(
                    "success", full=full
                )
                self.assertEqual(code, 0)
                self.assertEqual(result["status"], "concluido")
                self.assertTrue(result["fluxo_completo"])
                self.assertEqual(calls[-1], ["app/run_main.py"])
                self.assertTrue(state["contacts"]["u1"]["orders"]["100"]["admitted"])
                self.assertEqual(len(posts), 2)
                self.assertEqual(events[-1]["status"], "APLICADO")

    def test_legacy_strict_gate_reproduces_reported_stop_before_application(self):
        code, result, state, calls, posts, _ = self.run_scenario("legacy_strict")
        self.assertEqual(code, 3)
        self.assertFalse(result["fluxo_completo"])
        self.assertIn("--dry-run", calls[-1])
        self.assertEqual(state["contacts"], {})
        self.assertEqual(posts, [])

    def test_partial_queries_apply_valid_contact_and_complete_final_analytics(self):
        for full in (False, True):
            with self.subTest(full=full):
                code, result, state, calls, posts, _ = self.run_scenario(
                    "partial_queries", full=full
                )
                self.assertEqual(code, 3)
                self.assertTrue(result["fluxo_completo"])
                self.assertEqual(calls[-1], ["app/run_main.py"])
                self.assertEqual(result["etapas"][-2]["codigo"], 3)
                self.assertEqual(result["etapas"][-1]["codigo"], 0)
                self.assertEqual(
                    result["etapas"][7]["consultas_incompletas"]["motivos_consulta"],
                    {"ERRO_ITENS_PEDIDO_API": 1},
                )
                self.assertNotIn("synthetic-broken", state["contacts"])
                self.assertTrue(state["contacts"]["u1"]["orders"]["100"]["admitted"])
                self.assertEqual(len(posts), 2)

    def test_live_order_change_is_not_applied_from_the_old_review(self):
        code, result, state, calls, posts, _ = self.run_scenario("source_changed")
        self.assertEqual(code, 3)
        self.assertTrue(result["fluxo_completo"])
        self.assertEqual(calls[-1], ["app/run_main.py"])
        self.assertEqual(posts, [])
        self.assertEqual(state["contacts"], {})

    def test_tampered_review_stops_before_any_post_or_final_analytics(self):
        code, result, state, calls, posts, _ = self.run_scenario("tampered_review")
        self.assertEqual(code, 1)
        self.assertFalse(result["fluxo_completo"])
        self.assertIn("--check-review", calls[-1])
        self.assertEqual(posts, [])
        self.assertEqual(state["contacts"], {})

    def test_uncertain_post_stops_and_preserves_duplicate_protection(self):
        code, result, state, calls, posts, events = self.run_scenario("uncertain_post")
        self.assertEqual(code, 1)
        self.assertFalse(result["fluxo_completo"])
        self.assertIn("--apply", calls[-1])
        adds = [
            call
            for call in posts
            if call[1] == WENI_CONTACT_ACTIONS_API_URL and call[3]["action"] == "add"
        ]
        self.assertEqual(len(adds), 1)
        entry = state["contacts"]["u1"]["orders"]["100"]
        self.assertTrue(entry["pending"])
        self.assertFalse(entry.get("admitted", False))
        self.assertEqual(events[-1]["status"], "FALHA_OU_RESULTADO_INDETERMINADO")
        self.assertEqual(events[-1]["stage"], "confirmar_inclusao_no_grupo")
