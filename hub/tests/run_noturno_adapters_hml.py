"""Manual integration with two disposable test DBs. Never use a deployed Hub DSN."""
# ruff: noqa: E402

import json
import os
import sys

import psycopg
import synthetic_settings

sys.modules["secrets_config"] = synthetic_settings
os.environ["NEXOFLOW_PERFIL"] = "FARMA"
from nexoflow_hub.config import Settings
from nexoflow_hub.store import Store
from nexoflow_hub.worker import run_once
from psycopg.conninfo import conninfo_to_dict

for env, db in (
    ("TEST_HUB_DSN", "nexoflow_hub_hml_paridade4"),
    ("TEST_PUB_DSN", "nexoflow_datastudio_homologacao"),
):
    dsn = os.environ[env]
    assert conninfo_to_dict(dsn)["dbname"] == db
    with psycopg.connect(dsn) as conn:
        assert conn.execute(
            "SELECT current_database(), current_setting('nexoflow.test_instance',true)"
        ).fetchone() == (db, "isolated_synthetic_only")
s = Store(
    Settings(
        os.environ["TEST_HUB_DSN"],
        {"FARMA": "f" * 40, "PET": "p" * 40},
        lease_seconds=120,
        noturno_test_dsn=os.environ["TEST_PUB_DSN"],
    )
)
s.migrate()
for scenario in [
    "reserva_isolada",
    "reserva_anuncios_incompletos",
    "recompra_resposta_perdida",
    "resposta_incerta",
]:
    t = s.create("FARMA", "teste", "paridade4-" + scenario, scenario, noturno=True)
    print("CASE", scenario, t["id"], flush=True)
    assert run_once(s)
    d = s.get("FARMA", t["id"])
    print(
        "RESULT",
        scenario,
        d["estado"],
        json.dumps(d["resultado"], default=str, ensure_ascii=False),
        flush=True,
    )
    assert (
        d["estado"]
        == dict(
            reserva_isolada="parcial",
            reserva_anuncios_incompletos="parcial",
            recompra_resposta_perdida="concluida",
            resposta_incerta="revisao_necessaria",
        )[scenario]
    )
    from nexoflow_hub.central import read_summary

    current = next(
        x
        for x in read_summary(s.settings.dsn, "FARMA")["tarefas"]
        if x["id"] == t["id"]
    )
    print("CENTRAL", json.dumps(current, ensure_ascii=False, default=str), flush=True)
    assert (
        s.create("FARMA", "teste", "paridade4-" + scenario, scenario, noturno=True)[
            "id"
        ]
        == t["id"]
    )
