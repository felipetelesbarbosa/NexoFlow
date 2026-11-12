"""Integração real com PostgreSQL temporário; nenhum destino comercial é usado."""

# ruff: noqa: E402 -- dependências PostgreSQL opcionais verificadas antes dos imports
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from bi_postgres_client import Publisher
from bi_postgres_contract import (
    PROTOCOL,
    TARGET,
    PublicationError,
    digest,
    validate_payload,
)
from integrations.bi_itens_publisher.api import create_app
from integrations.bi_itens_publisher.store import Store, migrate

TOKEN = "credencial-exclusivamente-sintetica-" + ("x" * 32)


def row(n=1, sale=1, **kw):
    data = dict(
        item_chave=f"{n:032x}",
        venda_chave=f"{sale:032x}",
        cliente_chave=f"{99:032x}",
        data="2026-11-01",
        produto_codigo="000123",
        produto_nome="Produto sintético",
        categoria="Teste",
        quantidade="2",
        valor_unitario="1.25",
        receita_item="2.50",
        sku_informado=1,
        atualizado_em="2026-11-12T10:00:00-03:00",
    )
    data.update(kw)
    return list(data.values())


@pytest.fixture
def store():
    dsn = os.environ.get("NEXOFLOW_PUBLISHER_TEST_DSN")
    if not dsn:
        pytest.skip("PostgreSQL temporário não configurado")
    # Aceita somente o banco temporário preparado pelo roteiro/CI.
    with psycopg.connect(dsn) as c:
        assert (
            c.execute("SELECT current_database()").fetchone()[0]
            == "nexoflow_datastudio_piloto"
        )
        assert (
            c.execute(
                "SELECT current_setting('nexoflow.test_instance',true)"
            ).fetchone()[0]
            == "isolated_synthetic_only"
        )
        assert (
            c.execute("SELECT current_setting('application_name')").fetchone()[0]
            == "nexoflow-publisher-tests"
        )
        c.execute("DROP SCHEMA IF EXISTS nexoflow_publicacao CASCADE")
        c.execute("DROP SCHEMA IF EXISTS farma CASCADE")
        c.execute("CREATE SCHEMA farma")
        c.execute("""CREATE TABLE farma.bi_itens(item_chave text PRIMARY KEY,venda_chave text NOT NULL,
         cliente_chave text NOT NULL,data date NOT NULL,produto_codigo text NOT NULL,
         produto_nome text NOT NULL,categoria text NOT NULL,quantidade numeric NOT NULL,
         valor_unitario numeric NOT NULL,receita_item numeric NOT NULL,sku_informado integer NOT NULL,
         atualizado_em timestamptz NOT NULL)""")
        c.execute("CREATE VIEW farma.produtos_itens AS SELECT * FROM farma.bi_itens")
    migrate(dsn)
    return Store(dsn)


def payload(store, rows=None, complete=True, sales=None, session=None):
    session = session or store.session(str(uuid4()))["session_id"]
    return {
        "protocol": PROTOCOL,
        "target": TARGET,
        "segment": "FARMA",
        "batch_id": str(uuid4()),
        "session_id": session,
        "complete": complete,
        "sales": sales if sales is not None else [f"{1:032x}"],
        "rows": rows if rows is not None else [row()],
    }


def submit(store, payload, *, simulate=False):
    if not simulate:
        store.plan(
            payload["session_id"],
            [
                {
                    "batch_id": payload["batch_id"],
                    "digest": digest(validate_payload(payload)),
                }
            ],
            payload["complete"],
        )
    return store.apply(payload, simulate=simulate)


def facts(store):
    with store.connect() as c:
        return c.execute("SELECT * FROM farma.bi_itens ORDER BY item_chave").fetchall()


def test_replay_zero_changes_and_business_updates(store):
    p = payload(store)
    a = submit(store, p)
    assert a["inseridos"] == 1 and a["confirmed"] is True
    with store.connect() as c:
        version = c.execute("SELECT xmin::text AS v FROM farma.bi_itens").fetchone()[
            "v"
        ]
    assert submit(store, p) == a
    with store.connect() as c:
        assert (
            c.execute("SELECT xmin::text AS v FROM farma.bi_itens").fetchone()["v"]
            == version
        )
    assert len(facts(store)) == 1
    same = payload(store, [row(atualizado_em="2026-11-13T10:00:00-03:00")])
    receipt = submit(store, same)
    assert (receipt["inseridos"], receipt["atualizados"], receipt["mantidos"]) == (
        0,
        0,
        1,
    )
    with store.connect() as c:
        assert (
            c.execute("SELECT xmin::text AS v FROM farma.bi_itens").fetchone()["v"]
            == version
        )
    assert facts(store)[0]["produto_codigo"] == "000123"
    assert facts(store)[0]["receita_item"] == Decimal("2.50")
    changed = payload(store, [row(receita_item="4.50", quantidade="3")])
    assert submit(store, changed)["atualizados"] == 1
    assert facts(store)[0]["receita_item"] == Decimal("4.50")


def test_reconcile_changed_key_removed_item_cancelled_order_and_rollback(store):
    p = payload(store, [row(1), row(2)])
    submit(store, p)
    corrected = payload(store, [row(3)])
    r = submit(store, corrected)
    assert (r["inseridos"], r["removidos"]) == (1, 2)
    assert [f["item_chave"] for f in facts(store)] == [f"{3:032x}"]
    cancelled = payload(store, [])
    assert submit(store, cancelled)["removidos"] == 1
    assert facts(store) == []
    assert store.rollback(cancelled["batch_id"])["state"] == "REVERTIDO"
    assert len(facts(store)) == 1
    with pytest.raises(PublicationError, match="REVERTIDO"):
        submit(store, cancelled)


def test_partial_never_deletes_or_reconciles_outside_scope(store):
    submit(
        store,
        payload(
            store, [row(1), row(2), row(3, sale=2)], sales=[f"{1:032x}", f"{2:032x}"]
        ),
    )
    r = submit(store, payload(store, [row(1)], complete=False))
    assert r["removidos"] == 0 and r["remocoes_bloqueadas"] == 1
    assert len(facts(store)) == 3
    submit(store, payload(store, []))
    assert [f["venda_chave"] for f in facts(store)] == [f"{2:032x}"]


def test_old_batches_cannot_overwrite_new_correction_or_resurrect_cancelled(store):
    older = payload(store)
    newer = payload(store, [row(receita_item="9.99")])
    submit(store, newer)
    with pytest.raises(PublicationError, match="ANTIGO"):
        submit(store, older)
    assert facts(store)[0]["receita_item"] == Decimal("9.99")
    older2 = payload(store, [row()])
    submit(store, payload(store, []))
    with pytest.raises(PublicationError, match="ANTIGO"):
        submit(store, older2)
    assert facts(store) == []


def test_conflicting_reuse_or_order_identity_rejected_atomically(store):
    p = payload(store)
    submit(store, p)
    altered = {**p, "rows": [row(receita_item="100.00")]}
    with pytest.raises(PublicationError, match="DIVERGENTE"):
        submit(store, altered)
    with pytest.raises(PublicationError, match="TROCOU"):
        submit(store, payload(store, [row(sale=2)], sales=[f"{2:032x}"]))
    assert facts(store)[0]["receita_item"] == Decimal("2.50")


def test_simulation_and_invalid_payload_never_change_facts(store):
    p = payload(store)
    r = submit(store, p, simulate=True)
    assert r["state"] == "SIMULADO" and r["confirmed"] is False and r["inseridos"] == 1
    assert facts(store) == [] and store.receipt(p["batch_id"]) is None
    for changed in [
        {"segment": "PET"},
        {"target": "nexoflow_hub.farma.bi_itens"},
        {"rows": [row(receita_item="NaN")]},
        {"rows": [row(), row()]},
    ]:
        with pytest.raises(PublicationError):
            submit(store, {**p, **changed})
    assert facts(store) == []


def test_rollback_refuses_later_edit(store):
    p = payload(store)
    submit(store, p)
    submit(store, payload(store, [row(receita_item="12.34")]))
    with pytest.raises(PublicationError, match="EDICAO_POSTERIOR"):
        store.rollback(p["batch_id"])
    assert facts(store)[0]["receita_item"] == Decimal("12.34")


def test_failure_before_commit_has_no_rows_or_receipt(store):
    p = payload(store)
    with store.connect() as c:
        c.execute(
            "ALTER TABLE farma.bi_itens ADD CONSTRAINT teste_falha CHECK(receita_item<2)"
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        submit(store, p)
    assert facts(store) == [] and store.receipt(p["batch_id"]) is None


class Transport:
    def __init__(self, store):
        self.http = TestClient(create_app(store, TOKEN))
        self.post_batches = 0
        self.lose = False
        self.requests = []

    def request(self, method, url, **kw):
        import requests

        self.requests.append((method, url))
        kw.pop("timeout", None)
        kw["follow_redirects"] = kw.pop("allow_redirects")
        response = self.http.request(method, url, **kw)
        if method == "POST" and url.endswith("/lotes"):
            self.post_batches += 1
            if self.lose:
                raise requests.ConnectionError(
                    "Segredo sintético que não pode aparecer em log"
                )
        return response

    def close(self):
        self.http.close()


def credentials():
    return dict(
        endpoint="https://private.example.test",
        publish_token=TOKEN,
        access_client_id="fixture.access",
        access_client_secret="fixture-only",
    )


def test_windows_lost_response_after_commit_resumes_without_post_or_checkpoint(
    store, tmp_path, caplog
):
    state = tmp_path / "outbox.json"
    transport = Transport(store)
    client = Publisher(
        credentials(),
        state,
        simulate=False,
        transport=transport,
        sleeper=lambda _: None,
    )
    client.start()
    transport.lose = True
    with pytest.raises(PublicationError, match="INCERTA"):
        client.publish([row()], [f"{1:032x}"], complete=True)
    saved = json.loads(state.read_text())
    assert saved["receipts"] == {} and saved["status"] == "PENDENTE"
    assert len(facts(store)) == 1
    before = transport.post_batches
    transport.lose = False
    client.close()  # Encerramento do processo libera o lock local antes da retomada.
    next_transport = Transport(store)
    restarted = Publisher(
        credentials(),
        state,
        simulate=False,
        transport=next_transport,
        sleeper=lambda _: None,
    )
    restarted.start()
    assert transport.post_batches == before
    assert next_transport.post_batches == 0
    assert json.loads(state.read_text())["status"] == "CONFIRMADO"
    assert "Segredo sintético" not in caplog.text
    assert len(facts(store)) == 1


def test_windows_simulation_no_outbox_and_auth_required(store, tmp_path):
    transport = Transport(store)
    client = Publisher(credentials(), tmp_path / "outbox.json", transport=transport)
    client.start()
    r = client.publish([row()], [f"{1:032x}"], complete=True)
    assert r["simulated"] and not client.path.exists() and facts(store) == []
    denied = transport.http.post(
        "/publicacao/farma/bi-itens/lotes", json=payload(store)
    )
    assert denied.status_code == 401 and facts(store) == []


def test_schema_wrong_database_or_unknown_columns_fail_closed(store):
    with store.connect() as c:
        c.execute("ALTER TABLE farma.bi_itens ADD COLUMN inesperado text")
    with pytest.raises(PublicationError, match="SCHEMA"):
        submit(store, payload(store))


def test_same_session_sale_cannot_receive_conflicting_batch(store):
    first = payload(store)
    submit(store, first)
    with pytest.raises(PublicationError, match="ESCOPO_REUTILIZADO|PLANO_DIVERGENTE"):
        submit(
            store,
            payload(store, [row(receita_item="99.00")], session=first["session_id"]),
        )
    assert facts(store)[0]["receita_item"] == Decimal("2.50")


def test_two_concurrent_retries_commit_once(store):
    from concurrent.futures import ThreadPoolExecutor

    p = payload(store)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = list(pool.map(lambda value: submit(store, value), [p, p]))
    assert a == b and len(facts(store)) == 1


def test_dedicated_database_role_has_only_required_privileges(store):
    import secrets

    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    password = secrets.token_hex(24)
    with store.connect() as c:
        if not c.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='nf_bi_itens_publisher'"
        ).fetchone():
            c.execute(
                "CREATE ROLE nf_bi_itens_publisher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
        c.execute(
            sql.SQL("ALTER ROLE nf_bi_itens_publisher PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        c.execute(Path("integrations/bi_itens_publisher/grants.sql").read_text())
        c.execute("CREATE SCHEMA outro_destino")
        c.execute("CREATE TABLE outro_destino.protegida(valor text)")
    params = conninfo_to_dict(store.dsn)
    params.update(user="nf_bi_itens_publisher", password=password)
    limited = Store(make_conninfo(**params))
    p = payload(limited)
    assert submit(limited, p)["inseridos"] == 1
    assert submit(limited, p)["inseridos"] == 1  # Mesmo recibo; não é nova inserção.
    assert len(facts(store)) == 1
    with limited.connect() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT * FROM outro_destino.protegida")
    with limited.connect() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("CREATE TABLE farma.proibida(x int)")
    with limited.connect() as c:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM nexoflow_publicacao.batches")


def test_real_api_container_starts_read_only_and_commits_with_dedicated_role(
    store, reader, tmp_path
):
    import secrets
    import subprocess
    import time

    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    image = os.environ.get("NEXOFLOW_PUBLISHER_TEST_IMAGE")
    if not image:
        pytest.skip("Smoke do contêiner executado com --image")

    def start_container(command, **options):
        result = subprocess.run(command, **options)
        if result.returncode:
            detail = (
                result.stderr.decode(errors="replace")
                .replace(password, "[sintético]")
                .replace(TOKEN, "[sintético]")
            )
            pytest.fail("Docker não iniciou o serviço temporário: " + detail[:1200])
        return result

    password = secrets.token_hex(24)
    with store.connect() as c:
        if not c.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='nf_bi_itens_publisher'"
        ).fetchone():
            c.execute(
                "CREATE ROLE nf_bi_itens_publisher LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
        c.execute(
            sql.SQL("ALTER ROLE nf_bi_itens_publisher PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        c.execute(Path("integrations/bi_itens_publisher/grants.sql").read_text())
    params = conninfo_to_dict(store.dsn)
    params.update(user="nf_bi_itens_publisher", password=password)
    dsn = make_conninfo(**params)
    limited = Store(dsn, require_dedicated_role=True)
    with pytest.raises(PublicationError, match="PRIVILEGIOS"):
        with store.connect() as c:
            Store(store.dsn, require_dedicated_role=True).check(c)
    folder = tmp_path / "container-secrets"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)
    tmp_path.chmod(0o755)
    # Somente segredos sintéticos do banco temporário; montagem acessível ao UID sem root.
    for filename, content in [("dsn", dsn), ("token", TOKEN)]:
        f = folder / filename
        f.write_text(content)
        f.chmod(0o444)
    name = "nf-bi-api-test-" + uuid4().hex[:12]
    start_container(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--mount",
            f"type=bind,src={folder},dst=/run/secrets,readonly",
            "-e",
            "PUBLISH_DSN_FILE=/run/secrets/dsn",
            "-e",
            "PUBLISH_TOKEN_FILE=/run/secrets/token",
            image,
        ],
        capture_output=True,
    )
    # O teste mantém o bloqueio de rede Python da suíte. O HTTP real ocorre
    # somente no loopback do contêiner descartável que acabamos de criar.
    script = """
import json,sys,pathlib,urllib.request,urllib.error
v=json.load(sys.stdin);headers={'Content-Type':'application/json'}
if v['authorized']:headers['Authorization']='Bearer '+pathlib.Path('/run/secrets/token').read_text().strip()
data=json.dumps(v['payload']).encode() if v['payload'] is not None else None
r=urllib.request.Request('http://127.0.0.1:8080'+v['path'],data=data,headers=headers,method=v['method'])
try:
 response=urllib.request.urlopen(r,timeout=10)
except urllib.error.HTTPError as e:
 response=e
print(json.dumps({'code':response.status,'body':json.load(response)}))
"""

    current_container = name

    def http(method, path, data=None, authorized=True):
        output = subprocess.check_output(
            ["docker", "exec", "-i", current_container, "python", "-c", script],
            input=json.dumps(
                {
                    "method": method,
                    "path": path,
                    "payload": data,
                    "authorized": authorized,
                }
            ),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return json.loads(output)

    reader_name = None
    try:
        r = {"code": 0, "body": {}}
        for _ in range(40):
            try:
                r = http("GET", "/publicacao/destino")
                if r["code"] == 200:
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.25)
        else:
            logs = subprocess.run(
                ["docker", "logs", name], capture_output=True, text=True
            ).stderr
            print(
                logs.replace(password, "[sintético]").replace(TOKEN, "[sintético]")[
                    -4000:
                ]
            )
            pytest.fail(
                "API Docker não comprovou prontidão com usuário dedicado: " + str(r)
            )
        assert r["body"]["target"] == TARGET
        p = payload(limited)
        registered = http(
            "POST",
            "/publicacao/farma/bi-itens/planos",
            {
                "session_id": p["session_id"],
                "manifest": [
                    {"batch_id": p["batch_id"], "digest": digest(validate_payload(p))}
                ],
                "complete": p["complete"],
            },
        )
        assert registered["code"] == 200
        result = http("POST", "/publicacao/farma/bi-itens/lotes", p)
        assert result["code"] == 200 and result["body"]["confirmed"] is True
        assert len(facts(store)) == 1
        assert http("POST", "/publicacao/farma/bi-itens/lotes", p) == result
        assert len(facts(store)) == 1
        assert http("GET", "/publicacao/destino", authorized=False)["code"] == 401
        # O publicador já foi exercitado; liberar seus recursos antes do smoke do leitor.
        subprocess.run(["docker", "rm", "-f", name], check=True, capture_output=True)
        read_folder = tmp_path / "read-secrets"
        read_folder.mkdir(mode=0o755)
        read_folder.chmod(0o755)
        for filename, content in [("dsn", reader.dsn), ("token", TOKEN + "-read")]:
            f = read_folder / filename
            f.write_text(content)
            f.chmod(0o444)
        reader_name = name + "-reader"
        start_container(
            [
                "docker",
                "run",
                "-d",
                "--name",
                reader_name,
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--mount",
                f"type=bind,src={read_folder},dst=/run/secrets,readonly",
                "-e",
                "READ_DSN_FILE=/run/secrets/dsn",
                "-e",
                "READ_TOKEN_FILE=/run/secrets/token",
                image,
                "uvicorn",
                "integrations.bi_itens_publisher.read_api:app_factory",
                "--factory",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--no-access-log",
            ],
            capture_output=True,
        )
        current_container = reader_name
        for _ in range(40):
            try:
                r = http("GET", "/consulta/destino")
                if r["code"] == 200:
                    break
            except subprocess.CalledProcessError:
                pass
            time.sleep(0.25)
        else:
            pytest.fail("API de leitura não ficou pronta")
        result = http("POST", "/consulta/farma/bi-itens", query(["receita_item"]))
        assert result["code"] == 200 and result["body"]["rows"] == [
            {"values": ["2.50"]}
        ]
        assert http("POST", "/publicacao/farma/bi-itens/lotes", p)["code"] == 404
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
        if reader_name:
            subprocess.run(
                ["docker", "rm", "-f", reader_name], capture_output=True, check=False
            )


def test_staging_never_silently_rounds_precision(store):
    with store.connect() as c:
        c.execute("DROP VIEW farma.produtos_itens")  # Somente fixture descartável.
        c.execute("ALTER TABLE farma.bi_itens ALTER quantidade TYPE numeric(18,2)")
    with pytest.raises(PublicationError, match="PRECISAO"):
        submit(store, payload(store, [row(quantidade="1.123456")]))
    assert facts(store) == []


def test_user_trigger_or_rls_requires_review_without_writing(store):
    with store.connect() as c:
        c.execute("ALTER TABLE farma.bi_itens ENABLE ROW LEVEL SECURITY")
    with pytest.raises(PublicationError, match="ESTRUTURA"):
        submit(store, payload(store))
    assert facts(store) == []


@pytest.fixture
def reader(store):
    import secrets

    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    from integrations.bi_itens_publisher.reader import Reader

    password = secrets.token_hex(24)
    with store.connect() as c:
        if not c.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='nf_bi_itens_reader'"
        ).fetchone():
            c.execute(
                "CREATE ROLE nf_bi_itens_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS"
            )
        c.execute(
            sql.SQL("ALTER ROLE nf_bi_itens_reader PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        c.execute(Path("integrations/bi_itens_publisher/reader-grants.sql").read_text())
    params = conninfo_to_dict(store.dsn)
    params.update(user="nf_bi_itens_reader", password=password)
    return Reader(make_conninfo(**params))


def query(fields, *, start="2026-11-01", end="2026-11-03", filters=None):
    from integrations.bi_itens_publisher.reader import READ_PROTOCOL, READ_TARGET

    return {
        "protocol": READ_PROTOCOL,
        "target": READ_TARGET,
        "segment": "FARMA",
        "fields": fields,
        "start": start,
        "end": end,
        "filters": filters or [],
    }


def test_readonly_view_month_day_empty_distinct_and_rankings(store, reader):
    rows = [
        row(1, data="2026-11-01"),
        row(2, sale=2, data="2026-11-02"),
        row(3, sale=3, produto_codigo="000999", receita_item="5.25"),
    ]
    submit(store, payload(store, rows, sales=[f"{i:032x}" for i in (1, 2, 3)]))
    count = reader.query(query(["produtos_distintos_periodo"]))
    assert count["rows"] == [{"values": [2]}] and count["state"] == "READY"
    totals = reader.query(query(["quantidade", "receita_item"]))
    assert totals["rows"] == [{"values": ["6", "10.25"]}]
    ranks = reader.query(query(["produto_codigo", "quantidade", "receita_item"]))
    assert ranks["rows"] == [
        {"values": ["000123", "4", "5.00"]},
        {"values": ["000999", "2", "5.25"]},
    ]
    day = reader.query(
        query(["produtos_distintos_periodo"], start="2026-11-02", end="2026-11-02")
    )
    assert day["rows"] == [{"values": [1]}]
    empty = reader.query(
        query(["quantidade", "receita_item"], start="2026-11-30", end="2026-11-30")
    )
    assert empty["rows"] == []
    with reader.connect() as c:
        with pytest.raises(
            (
                psycopg.errors.InsufficientPrivilege,
                psycopg.errors.ReadOnlySqlTransaction,
            )
        ):
            c.execute("DELETE FROM farma.bi_itens")


def test_reader_filters_are_parameterized_and_fail_closed(store, reader):
    submit(
        store, payload(store, [row(produto_nome="x'); DELETE FROM farma.bi_itens; --")])
    )
    f = {
        "fieldName": "produto_nome",
        "operator": "CONTAINS",
        "type": "INCLUDE",
        "values": ["DELETE FROM"],
    }
    assert reader.query(query(["receita_item"], filters=[[f]]))["rows"] == [
        {"values": ["2.50"]}
    ]
    for change in [
        {"segment": "PET"},
        {"fields": ["credenciais"]},
        {"target": "nexoflow_hub.public.base"},
        {"start": "2026-02-31"},
        {"filters": [[{**f, "operator": "REGEXP_PARTIAL_MATCH"}]]},
    ]:
        with pytest.raises(PublicationError):
            reader.query({**query(["receita_item"]), **change})
    assert len(facts(store)) == 1


def test_reader_refuses_incomplete_or_partial_publication_and_recovers_same_plan(
    store, reader
):
    from bi_postgres_contract import digest, validate_payload

    session = store.session(str(uuid4()))["session_id"]
    one = payload(store, [row()], sales=[f"{1:032x}"], session=session)
    two = payload(store, [row(2, sale=2)], sales=[f"{2:032x}"], session=session)
    manifest = [
        {"batch_id": p["batch_id"], "digest": digest(validate_payload(p))}
        for p in (one, two)
    ]
    store.plan(session, manifest, True)
    store.apply(one)
    with pytest.raises(PublicationError, match="PUBLICACAO_PENDENTE"):
        reader.query(query(["receita_item"]))
    store.apply(two)
    assert reader.query(query(["receita_item"]))["rows"] == [{"values": ["5.00"]}]
    submit(store, payload(store, [row()], complete=False))
    with pytest.raises(PublicationError, match="PUBLICACAO_PENDENTE"):
        reader.query(query(["receita_item"]))


def test_reader_detects_duplicated_view_grain_without_deduplicating_revenue(
    store, reader
):
    submit(store, payload(store))
    with store.connect() as c:
        c.execute(
            "CREATE OR REPLACE VIEW farma.produtos_itens AS SELECT * FROM farma.bi_itens UNION ALL SELECT * FROM farma.bi_itens"
        )
    with pytest.raises(PublicationError, match="GRAO_INVALIDO"):
        reader.query(query(["receita_item"]))


def test_reader_api_cannot_publish_and_writer_token_cannot_read(store, reader):
    from integrations.bi_itens_publisher.read_api import create_app as create_reader

    read_token = TOKEN + "-reader-only"
    http = TestClient(create_reader(reader, read_token))
    assert (
        http.get(
            "/consulta/destino", headers={"Authorization": "Bearer " + TOKEN}
        ).status_code
        == 401
    )
    auth = {"Authorization": "Bearer " + read_token}
    assert http.get("/consulta/destino", headers=auth).status_code == 200
    assert (
        http.post(
            "/publicacao/farma/bi-itens/lotes", headers=auth, json=payload(store)
        ).status_code
        == 404
    )
    data = http.post(
        "/consulta/farma/bi-itens", headers=auth, json=query(["receita_item"])
    )
    assert data.status_code == 200 and data.json()["rows"] == []


def test_reader_large_detail_refuses_truncation_and_summary_remains_exact(
    store, reader
):
    with store.connect() as c:
        c.execute("""INSERT INTO farma.bi_itens SELECT md5(n::text),md5(n::text),md5('cliente'),
          '2026-11-01'::date,'000123','Sintético','Teste',1,1.01,1.01,1,now()
          FROM generate_series(1,200001) AS n""")
    with pytest.raises(PublicationError, match="LIMITE"):
        reader.query(query(["item_chave", "receita_item"]))
    totals = reader.query(query(["receita_item"]))
    assert Decimal(totals["rows"][0]["values"][0]) == Decimal("202001.01")


def test_empty_failed_plan_can_be_closed_without_facts_or_fake_ready(store, reader):
    p = payload(store)
    store.plan(
        p["session_id"],
        [{"batch_id": p["batch_id"], "digest": digest(validate_payload(p))}],
        True,
    )
    assert store.close_plan(p["session_id"]) == {
        "state": "REVERTIDO",
        "fatos_alterados": 0,
    }
    assert facts(store) == []
    with pytest.raises(PublicationError, match="PUBLICACAO_PENDENTE"):
        reader.query(query(["receita_item"]))
    submit(store, payload(store))
    assert reader.query(query(["receita_item"]))["rows"] == [{"values": ["2.50"]}]


def test_windows_archive_requires_server_proof_and_never_changes_facts(store, tmp_path):
    t = Transport(store)
    client = Publisher(
        credentials(),
        tmp_path / "outbox.json",
        simulate=False,
        transport=t,
        sleeper=lambda _: None,
    )
    client.start()
    client.publish([row()], [f"{1:032x}"], complete=True)
    with pytest.raises(PublicationError, match="NAO_ENCERRADA"):
        client.recover(archive_closed=True)
    saved = json.loads(client.path.read_text())
    store.rollback(saved["batches"][0]["batch_id"])
    result = client.recover(archive_closed=True)
    assert result["checkpoint_avancado"] is False and facts(store) == []
    assert list(tmp_path.glob("outbox-encerrada-*.json"))


def test_reader_optional_blank_text_keeps_sheet_semantics_without_inventing_identity(
    store, reader
):
    submit(store, payload(store))
    with store.connect() as c:
        from psycopg import sql

        from bi_postgres_contract import COLUMNS

        fields = [
            sql.SQL("NULL::text AS categoria")
            if name == "categoria"
            else sql.Identifier(name)
            for name in COLUMNS
        ]
        c.execute(
            sql.SQL(
                "CREATE OR REPLACE VIEW farma.produtos_itens AS SELECT {} FROM farma.bi_itens"
            ).format(sql.SQL(",").join(fields))
        )
    result = reader.query(query(["produto_codigo", "categoria", "receita_item"]))
    assert result["rows"] == [{"values": ["000123", "", "2.50"]}]


def test_builder_omission_does_not_delete_previous_facts_even_in_complete_plan(store):
    from bi_postgres_client import batches, sales_scope
    from looker_bi import build_looker_tables
    from tests.test_looker_bi import item, order

    def built(o):
        return build_looker_tables(
            [],
            [o],
            [item(1)],
            snapshot_date="2026-11-12",
            updated_at="2026-11-12T10:00:00-03:00",
        )["BI_Itens"]

    original = order(1)
    initial = built(original)
    assert initial
    submit(store, payload(store, initial, sales=[initial[0][1]]))
    previous = facts(store)
    future = dict(original, data_hora="2099-01-01T10:00:00-03:00")
    omitted = built(future)
    assert omitted == []
    sid = store.session(str(uuid4()))["session_id"]
    batch = batches(omitted, sales_scope([future], omitted), sid, True)[0]
    receipt = submit(store, batch)
    assert receipt["removidos"] == 0 and receipt["atualizados"] == 0
    assert facts(store) == previous
