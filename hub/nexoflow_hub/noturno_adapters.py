"""Adapters of the Windows rules for the FARMA synthetic test destination only."""

from __future__ import annotations

import json
import os
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import uuid5

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

DB = "nexoflow_datastudio_homologacao"
MARKER = "isolated_synthetic_only"
GROUPS = {"g-in": "Opt-In LGPD", "g-out": "Opt-Out LGPD", "g-recompra": "Recompra D+25"}


def check_destination(conn):
    row = conn.execute(
        "SELECT current_database() AS db, current_setting('nexoflow.test_instance',true) AS marker"
    ).fetchone()
    if isinstance(row, dict):
        row = (row["db"], row["marker"])
    if row != (DB, MARKER):
        raise RuntimeError("DESTINO_SINTETICO_OBRIGATORIO")


class PublicationUncertain(Exception):
    def __init__(self, evidence):
        self.evidence = evidence


class Adapters:
    def __init__(self, hub, task):
        from integrations.datastudio.reader import create_views
        from integrations.datastudio.store import Store, migrate

        if task["segmento"] != "FARMA" or not hub.settings.noturno_test_dsn:
            raise RuntimeError("DESTINO_SINTETICO_OBRIGATORIO")
        dsn = hub.settings.noturno_test_dsn
        info = conninfo_to_dict(dsn)
        if (
            info.get("dbname") != DB
            or info.get("host") not in {"noturno-pg-teste", "127.0.0.1"}
            or info.get("hostaddr")
            or info.get("service")
        ):
            raise RuntimeError("DESTINO_SINTETICO_OBRIGATORIO")
        self.hub, self.task = hub, task
        self.scenario = task["cenario"]
        self.fence()
        with psycopg.connect(dsn) as conn:
            check_destination(conn)
            conn.execute("CREATE SCHEMA IF NOT EXISTS ensaio")
            conn.execute("""CREATE TABLE IF NOT EXISTS ensaio.weni (
                tarefa uuid NOT NULL, contato uuid NOT NULL, documento jsonb NOT NULL,
                PRIMARY KEY(tarefa, contato))""")
            conn.execute("""CREATE TABLE IF NOT EXISTS ensaio.acoes (
                id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                tarefa uuid NOT NULL, contato uuid NOT NULL, acao text NOT NULL, detalhe jsonb)""")
        migrate(dsn, "homologacao")
        with psycopg.connect(dsn) as conn:
            check_destination(conn)
            create_views(conn)

        class GuardedPublisher(Store):
            @contextmanager
            def connect(self, *, readonly=False):
                with super().connect(readonly=readonly) as conn:
                    check_destination(conn)
                    yield conn

        self.pub = GuardedPublisher(dsn, "homologacao", "FARMA")
        self.root = Path(os.environ["HUB_NOTURNO_TEST_STATE_DIR"]) / str(task["id"])
        self.root.mkdir(parents=True, exist_ok=True)

    def fence(self):
        with self.hub.connect() as conn:
            self.hub.fenced(conn, self.task)

    def uid(self, label):
        return str(uuid5(self.task["id"], label))

    def seed(self, contact):
        self.fence()
        with self.pub.connect() as conn:
            conn.execute(
                "INSERT INTO ensaio.weni VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (self.task["id"], contact["uuid"], Jsonb(contact)),
            )

    def get_contact(self, *, uuid=None, urn=None):
        self.fence()
        with self.pub.connect(readonly=True) as conn:
            row = conn.execute(
                "SELECT documento FROM ensaio.weni WHERE tarefa=%s AND contato=%s",
                (self.task["id"], uuid),
            ).fetchone()
            return row["documento"] if row else None

    def mutate(self, uid, action, detail):
        self.fence()
        with self.pub.connect() as conn:
            row = conn.execute(
                "SELECT documento FROM ensaio.weni WHERE tarefa=%s AND contato=%s FOR UPDATE",
                (self.task["id"], uid),
            ).fetchone()
            if not row:
                raise RuntimeError("CONTATO_TESTE_AUSENTE")
            c = row["documento"]
            if action == "fields":
                c["fields"].update(detail)
            else:
                groups = {g["uuid"] for g in c["groups"]}
                if action == "add" and detail in groups or action == "remove" and detail not in groups:
                    return c
                c["groups"] = [g for g in c["groups"] if g["uuid"] != detail]
                if action == "add":
                    c["groups"].append({"uuid": detail, "name": GROUPS[detail]})
            conn.execute(
                "UPDATE ensaio.weni SET documento=%s WHERE tarefa=%s AND contato=%s",
                (Jsonb(c), self.task["id"], uid),
            )
            conn.execute(
                "INSERT INTO ensaio.acoes(tarefa,contato,acao,detalhe) VALUES(%s,%s,%s,%s)",
                (self.task["id"], uid, action, Jsonb(detail)),
            )
        return c

    def update_contact_fields(self, uid, fields):
        return self.mutate(uid, "fields", fields)

    def contact_group_action(self, uid, *, action, group):
        import requests

        self.mutate(uid, action, group)
        if (
            self.scenario == "recompra_resposta_perdida"
            and group == "g-recompra"
            and action == "add"
        ):
            # The write was committed in the test DB before the response was lost.
            raise requests.Timeout("resposta sintética perdida após inclusão")
        return {"ok": True}

    def count(self, uid, action):
        with self.pub.connect(readonly=True) as conn:
            return conn.execute(
                "SELECT count(*) AS n FROM ensaio.acoes WHERE tarefa=%s AND contato=%s AND acao=%s",
                (self.task["id"], uid, action),
            ).fetchone()["n"]

    def update(self):
        import weni_update as wu
        from reservas_farma import Reservas

        reserve = self.scenario in {"reserva_isolada", "reserva_anuncios_incompletos"}
        uid = self.uid("update")
        original = {
            "uuid": uid,
            "name": "Contato sintético",
            "urns": ["whatsapp:+5591999999999"],
            "fields": {"opt_in_lgpd": "ativo", "marketing_opt_in": ""},
            "groups": [{"uuid": "g-out", "name": GROUPS["g-out"]}],
        }
        self.seed(original)
        reservations = Reservas(
            "synthetic", frozenset({uid}) if reserve else frozenset()
        )
        kwargs = dict(
            opt_in_group_name=GROUPS["g-in"],
            opt_in_group_uuid="g-in",
            opt_out_group_name=GROUPS["g-out"],
            opt_out_group_uuid="g-out",
        )
        plan = wu._build_contact_plan(
            original,
            context_messages=[],
            candidate_message_ids=set(),
            farm_client=None,
            captured_at="2026-10-09T13:57:00-03:00",
            **kwargs,
        )
        wu.audit_plans(
            [plan], opt_out_group_available=True, opt_in_group_available=True
        )
        if not reservations.protege(uid):
            pending, conflict = wu._prepare_frozen_plan_for_apply(
                plan, self.get_contact(uuid=uid), **kwargs
            )
            if pending is None:
                raise RuntimeError("PLANO_TESTE_DIVERGENTE")
            if pending.fields or pending.group_actions:
                wu._execute_contact_plan(self, pending)
        else:
            if self.get_contact(uuid=uid) != original or not any(
                a.action == "remove" for a in plan.group_actions
            ):
                raise RuntimeError("RESERVA_TESTE_DIVERGENTE")
        receipt = self.publish("atualizacao_weni", {"reservas": int(reserve)})
        return {
            "regra": "weni_update",
            "reservas": int(reserve),
            "recibo": receipt,
            "pendencias": [
                {
                    "fonte": "weni",
                    "motivo": "RESERVA_FARMA",
                    "tratamento": "proxima_carga",
                    "acao": "remover_grupo_optout",
                }
            ]
            if reserve
            else [],
        }

    def recompra(self):
        import recompra as rc

        uid = self.uid("recompra")
        now = datetime(2026, 10, 9, 13, 57, tzinfo=rc.TZ)
        GROUPS["g-recompra"] = rc.GROUP
        structure = {
            "group_uuid": "g-recompra",
            "opt_out_uuid": "g-out",
            "event_uuid": "event",
            "delivery_hour": -1,
            "event_signature": "signature",
            "errors": [],
        }
        contact = {
            "uuid": uid,
            "name": "Cliente sintético",
            "urns": ["tel:+5591999999999"],
            "fields": {"cpf": "52998224725", "marketing_opt_in": ""},
            "groups": [],
        }
        order = {
            "pedido_id": "100",
            "pedido_chave": "FARMALIDER:100",
            "data_hora": (now - timedelta(days=25) + timedelta(minutes=1)).isoformat(),
            "cpf_normalizado": "52998224725",
            "farmalider_status_pedido": "2",
            "farmalider_forma_pagamento": "3",
            "status_confirmacao": "CONFIRMADO_API",
            "status_validacao": "OK",
            "farmalider_cliente_id": "1",
            "valor_total_compra": "10",
        }
        items = [
            {
                "produto_nome": "Produto sintético, 30 cápsulas",
                "quantidade": "1",
                "valor_unitario": "10",
                "valor_total": "10",
            }
        ]
        self.seed(contact)
        state_path = self.root / "recompra.json"

        def apply():
            state = rc.load_state(state_path)
            live = self.get_contact(uuid=uid)
            plan = rc.propose(
                live,
                order,
                items,
                structure,
                rc._saved_with_purchase_check(state, uid),
                now=now,
            )
            review = rc.make_review([plan], structure, now=now, state=state)
            return rc.apply_review(
                review,
                self,
                SimpleNamespace(),
                state_path=state_path,
                audit_path=self.root / "audit.jsonl",
                pending_report_path=self.root / "pending.json",
                now_fn=lambda: now,
                read_structure=lambda _: structure,
                resolve_checked_contact=lambda *a, **k: (
                    deepcopy(order),
                    deepcopy(items),
                ),
            )

        recovered = False
        try:
            apply()
        except RuntimeError as exc:
            if (
                self.scenario != "recompra_resposta_perdida"
                or "adicionar_grupo" not in str(exc)
            ):
                raise
            apply()
            recovered = True
        count = self.count(uid, "add")
        admitted = rc.load_state(state_path)["contacts"][uid]["orders"]["100"][
            "admitted"
        ]
        if count != 1 or not admitted:
            raise RuntimeError("ADMISSAO_TESTE_NAO_CONFIRMADA")
        return {
            "regra": "recompra.apply_review",
            "inclusoes_teste": count,
            "releitura_apos_resposta_perdida": recovered,
            "recibo": self.publish("recompra", {"inclusoes": count}),
        }

    def publish(self, stage, detail, *, uncertain=False):
        import requests
        from fastapi.testclient import TestClient

        from ds_backend.adapter import PostgresStore
        from ds_backend.client import Client
        from ds_backend.contract import PROTOCOL, REGISTRY, StorageError, digest
        from integrations.datastudio.api import create_app
        from publication_receipt import ready_receipt_matches

        self.fence()
        revision = self.uid(stage)
        status = self.pub.begin(
            revision, "teste", {"etapa": stage, "cenario": self.scenario}
        )
        if status["state"] == "READY":
            receipt = status["receipt"]
            if not ready_receipt_matches(
                receipt,
                revision=revision,
                manifest_hash=digest(status["sealed_manifest"]),
            ):
                raise RuntimeError("RECIBO_TESTE_DIVERGENTE")
            return receipt
        token = "synthetic-only-test-destination-" * 2
        api = TestClient(create_app(self.pub, token))
        owner = self

        class Transport:
            headers = {}
            attempts = 0
            lost = False

            def request(self, method, url, *, json=None, **_kwargs):
                owner.fence()
                path = urlsplit(url).path
                if uncertain and self.lost and path.startswith("/v1/revisoes/"):
                    self.attempts += 1
                    raise requests.Timeout("consulta de recibo indisponível no teste")
                response = api.request(method, path, json=json, headers=self.headers)
                if (
                    uncertain
                    and path == "/v1/confirmar"
                    and response.status_code == 200
                ):
                    self.lost = True
                    raise requests.Timeout("resposta final perdida no teste")
                return response

            def close(self):
                api.close()

        trans = Transport()
        client = Client(
            dict(
                endpoint="https://publisher.invalid",
                api_token=token,
                access_client_id="fixture",
                access_client_secret="fixture",
                environment="homologacao",
                segment="FARMA",
                protocol=PROTOCOL,
            ),
            session=trans,
        )
        adapter = PostgresStore(client, purpose="teste", revision=revision)
        row = {col: "" for col in REGISTRY["Controle"]["columns"]}
        row.update(
            chave=revision, valor=json.dumps(detail, sort_keys=True, ensure_ascii=False)
        )
        batch = client.send(
            revision, "Controle", [row], batch_id=self.uid(stage + "-batch")
        )
        adapter._receipts[batch["id"]] = batch["hash"]
        if stage in {"publicacao", "analytics_final"}:
            from decimal import Decimal

            from .core import evaluate

            validated = evaluate("FARMA", "normal")
            total = Decimal(validated["faturamento"])
            freight = Decimal(validated["frete"])
            if not validated["venda"]:
                raise RuntimeError("VENDA_TESTE_NAO_VALIDADA")
            sales = {col: "" for col in REGISTRY["BI_Vendas"]["columns"]}
            sales.update(
                data="2026-10-09",
                pedidos="1",
                pedidos_confirmados_api="1",
                clientes_compradores="1",
                unidades_vendidas="1",
                faturamento_produtos=str(total - freight),
                faturamento_frete=str(freight),
                faturamento_total=str(total),
                faturamento=str(total),
                faturamento_confirmado_api=str(total),
                ticket_medio=str(total),
                taxa_confirmacao_pct="100",
            )
            receipt = client.send(
                revision, "BI_Vendas", [sales], batch_id=self.uid(stage + "-sales")
            )
            adapter._receipts[receipt["id"]] = receipt["hash"]
        try:
            receipt = adapter.finish(complete=True)
        except StorageError:
            if uncertain and trans.lost and trans.attempts == 3:
                raise PublicationUncertain(
                    {
                        "revisao": revision,
                        "consultas_recibo": trans.attempts,
                        "recibo": None,
                    }
                ) from None
            raise
        finally:
            client.close()
        return receipt
