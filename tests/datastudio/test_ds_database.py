"""Somente PostgreSQL descartável identificado pelo script da suíte."""

import os
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from ds_backend.contract import SCHEMA_HASH, StorageError, digest
from integrations.datastudio.api import create_app
from integrations.datastudio.reader import Reader, create_views
from integrations.datastudio.store import Store, migrate
from tests.datastudio.test_contract import row

DSN = os.getenv("NEXOFLOW_DATASTUDIO_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not DSN, reason="PostgreSQL descartável não configurado"
)


@pytest.fixture
def store():
    assert DSN and "application_name=nexoflow-datastudio-tests" in DSN
    with psycopg.connect(DSN, autocommit=True) as conn:
        assert (
            conn.execute("SHOW nexoflow.test_instance").fetchone()[0]
            == "isolated_synthetic_only"
        )
        for schema in ("controle", "farma", "pet"):
            conn.execute("DROP SCHEMA IF EXISTS " + schema + " CASCADE")
    migrate(DSN, "homologacao")
    with psycopg.connect(DSN) as conn:
        create_views(conn)
    return Store(DSN, "homologacao", "FARMA")


def begin(s):
    return s.begin(str(uuid4()), "teste", {})["revision"]


def batch(s, rev, name, rows, **kwargs):
    return s.batch(rev, str(uuid4()), name, rows, **kwargs)


def finish(s, rev):
    with s.connect() as conn:
        receipts = conn.execute(
            "SELECT id,hash FROM controle.nf_lotes WHERE execucao=%s", (rev,)
        ).fetchall()
    return s.finish(
        rev,
        dict(
            schema_hash=SCHEMA_HASH,
            batches={str(r["id"]): r["hash"] for r in receipts},
            complete_sources=True,
        ),
        complete=True,
    )


def test_atomic_revision_repeat_and_rollback(store):
    rev = begin(store)
    item = row(
        "BI_Itens",
        item_chave="item-1",
        venda_chave="sale-1",
        data="2026-11-02",
        produto_codigo="0001",
        quantidade="2",
        receita_item="10.10",
        sku_informado="1",
    )
    bid = str(uuid4())
    first = store.batch(rev, bid, "BI_Itens", [item])
    assert first["inserted"] == 1
    assert store.batch(rev, bid, "BI_Itens", [item]) == first
    assert store.rows("BI_Itens")["rows"] == []
    assert store.rows("BI_Itens", revision=rev)["rows"] == [item]
    result = finish(store, rev)
    assert result["state"] == "READY"
    assert store.rows("BI_Itens")["rows"] == [item]
    rev2 = begin(store)
    assert batch(store, rev2, "BI_Itens", [item])["unchanged"] == 1
    corrected = dict(item, receita_item="10.20")
    assert batch(store, rev2, "BI_Itens", [corrected])["updated"] == 1
    # Enquanto WRITING, o leitor continua no snapshot anterior.
    assert store.rows("BI_Itens")["rows"] == [item]
    result2 = finish(store, rev2)
    assert store.rows("BI_Itens")["rows"] == [corrected]
    store.rollback(rev2, result2["version"])
    rev3 = begin(store)
    batch(store, rev3, "BI_Itens", [dict(item, quantidade="3")])
    finish(store, rev3)
    # Não ressuscitar a correção da revisão revertida.
    assert store.rows("BI_Itens")["rows"][0]["receita_item"] == "10.10"
    with pytest.raises(StorageError, match="EDICAO_POSTERIOR"):
        store.rollback(rev, result["version"])


def test_partial_manifest_wrong_segment_old_batch_and_simulation(store):
    rev = begin(store)
    item = row("BI_Itens", item_chave="1")
    simulated = batch(store, rev, "BI_Itens", [item], simulate=True)
    assert (
        simulated["state"] == "SIMULADO"
        and store.rows("BI_Itens", revision=rev)["rows"] == []
    )
    receipt = batch(store, rev, "BI_Itens", [item])
    with pytest.raises(StorageError, match="MANIFESTO"):
        store.finish(
            rev,
            dict(schema_hash=SCHEMA_HASH, batches={}, complete_sources=True),
            complete=True,
        )
    with pytest.raises(StorageError, match="INCOMPLETA"):
        store.finish(rev, {}, complete=False)
    other = Store(DSN, "homologacao", "PET")
    with pytest.raises(StorageError, match="AUSENTE"):
        other.batch(rev, str(uuid4()), "BI_Itens", [item])
    finish(store, rev)
    with pytest.raises(StorageError, match="FORA_DE_ORDEM"):
        batch(store, rev, "BI_Itens", [item])
    # O mesmo recibo pode ser consultado depois do commit sem repetir a escrita.
    assert store.receipt(receipt["id"]) == receipt


def test_replace_keeps_unchanged_members_and_removes_only_explicit_full_table(store):
    rev = begin(store)
    a = row("BI_Itens", item_chave="a")
    b = row("BI_Itens", item_chave="b")
    batch(store, rev, "BI_Itens", [a, b])
    finish(store, rev)
    rev2 = begin(store)
    store.replace(
        rev2,
        "BI_Itens",
        dict(
            count=1,
            sha256=digest(
                [
                    __import__(
                        "ds_backend.contract", fromlist=["record_key"]
                    ).record_key("BI_Itens", a)
                ]
            ),
        ),
    )
    batch(store, rev2, "BI_Itens", [a])
    finish(store, rev2)
    assert store.rows("BI_Itens")["rows"] == [a]
    with pytest.raises(StorageError, match="ACUMULADA"):
        store.replace(
            begin(store), "Historico_Pedidos", dict(count=0, sha256=digest([]))
        )


def test_sql_distinct_across_days_empty_and_no_partial(store):
    rev = begin(store)
    items = [
        row(
            "BI_Itens",
            item_chave=str(i),
            produto_codigo=sku,
            data=day,
            quantidade="1",
            receita_item="0.10",
            sku_informado="1",
        )
        for i, (sku, day) in enumerate(
            [("01", "2026-11-01"), ("01", "2026-11-02"), ("02", "2026-11-02")]
        )
    ]
    batch(store, rev, "BI_Itens", items)
    finish(store, rev)
    reader = Reader(DSN, "homologacao", "FARMA")
    result = reader.query(
        "BI_Itens",
        ["produto_codigo", "quantidade", "receita_item"],
        "2026-11-01",
        "2026-11-03",
        [dict(field="sku_informado", values=["1"])],
        dict(produto_codigo="count_distinct", quantidade="sum", receita_item="sum"),
    )
    assert result["rows"] == [[2, "3", "0.30"]]
    assert (
        reader.query("BI_Itens", ["item_chave"], "2026-11-30", "2026-11-30", [], {})[
            "rows"
        ]
        == []
    )
    with pytest.raises(StorageError):
        reader.query("Controle", ["chave"], "", "", [], {})


def test_api_auth_destination_no_secrets_and_reader_is_not_writer(store):
    token = "synthetic-only-token-not-used-elsewhere-12345"
    app = TestClient(create_app(store, token))
    assert app.get("/v1/destino").status_code == 401
    headers = {"Authorization": "Bearer " + token}
    assert (
        app.get("/v1/destino", headers=headers).json()["target"]
        == "nexoflow_datastudio_homologacao.farma"
    )
    response = app.post("/v1/lotes", headers=headers, json=dict(secret="DO_NOT_LOG"))
    assert response.status_code == 409 and "DO_NOT_LOG" not in response.text
    reader = TestClient(
        create_app(Reader(DSN, "homologacao", "FARMA"), token, reader=True)
    )
    assert reader.post("/v1/lotes", headers=headers, json={}).status_code == 404


def test_roles_rls_private_schema_and_read_views_only(store):
    from integrations.datastudio.admin import grants

    with store.connect() as conn:
        grants(conn, "FARMA")
        grants(conn, "PET")
    # Mesmas contas mínimas que serão usadas pelos contêineres, sem publicar porta.
    publisher_dsn = DSN + "&options=-c%20role%3Dnf_ds_farma_publish"
    reader_dsn = DSN + "&options=-c%20role%3Dnf_ds_farma_read"
    farma = Store(publisher_dsn, "homologacao", "FARMA", require_dedicated_role=True)
    assert farma.info()["segment"] == "FARMA"
    with farma.connect() as conn:
        assert conn.execute(
            "SELECT segmento FROM controle.nf_publicacoes"
        ).fetchall() == [{"segmento": "FARMA"}]
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM pet.nf_registros")
    # Falha anterior aborta só a conexão temporária do teste.
    with psycopg.connect(reader_dsn) as conn:
        assert conn.execute("SELECT count(*) FROM farma.ds_bi_itens").fetchone()[0] == 0
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM farma.nf_registros")
    assert (
        Reader(reader_dsn, "homologacao", "FARMA", require_dedicated_role=True).info()[
            "version"
        ]
        == 0
    )


def test_manifest_missing_replacement_batch_and_state_cas(store):
    from ds_backend.contract import record_key

    revision = begin(store)
    a = row("BI_Itens", item_chave="a")
    b = row("BI_Itens", item_chave="b")
    store.replace(
        revision,
        "BI_Itens",
        dict(
            count=2,
            sha256=digest(
                sorted([record_key("BI_Itens", a), record_key("BI_Itens", b)])
            ),
        ),
    )
    batch(store, revision, "BI_Itens", [a])
    with pytest.raises(StorageError, match="SUBSTITUICAO_INCOMPLETA"):
        finish(store, revision)
    assert store.rows("BI_Itens")["rows"] == []
    receipt_id = str(uuid4())
    first = store.state_put("weni_update", 0, {"cursor": "synthetic"}, receipt_id)
    assert (
        store.state_put("weni_update", 0, {"cursor": "synthetic"}, receipt_id) == first
    )
    with pytest.raises(StorageError, match="EDICAO_CONCORRENTE"):
        store.state_put("weni_update", 0, {}, str(uuid4()))
    assert store.state_get("weni_update")["document"] == {"cursor": "synthetic"}


def test_real_client_lost_response_receipt_and_wrong_target(store):
    import requests

    from ds_backend.client import Client

    token = "synthetic-only-token-not-used-elsewhere-12345"
    web = TestClient(create_app(store, token))
    lost = {"enabled": False}

    class Session:
        headers = {}

        def request(self, method, url, **kwargs):
            response = web.request(
                method,
                url.removeprefix("https://publish.example.invalid"),
                json=kwargs["json"],
                headers=self.headers,
            )
            if lost["enabled"] and url.endswith("/v1/lotes"):
                lost["enabled"] = False
                raise requests.ConnectionError("synthetic secret must not appear")
            return response

        def close(self):
            pass

    config = dict(
        endpoint="https://publish.example.invalid",
        api_token=token,
        access_client_id="synthetic.access",
        access_client_secret="synthetic-secret",
        environment="homologacao",
        segment="FARMA",
        protocol="nexoflow_datastudio_1",
    )
    client = Client(config, session=Session())
    revision = client.begin("teste")["revision"]
    lost["enabled"] = True
    receipt = client.send(
        revision, "BI_Itens", [row("BI_Itens", item_chave="synthetic")]
    )
    assert (
        receipt["inserted"] == 1
        and len(store.rows("BI_Itens", revision=revision)["rows"]) == 1
    )
    with pytest.raises(StorageError, match="CONTRATO_DESTINO_DIVERGENTE"):
        Client(dict(config, segment="PET"), session=Session())


def test_complete_history_union_keys_centavos_cancellation_and_client_ltv(store):
    from looker_bi import opaque_key

    rev = begin(store)
    history = [
        row(
            "Historico_Pedidos",
            chave="FARMA:" + oid,
            segmento="FARMA",
            pedido_id=oid,
            cliente_id="synthetic-owner",
            data=day,
            estado="valido",
            produtos=amount,
            frete="0.00",
            faturamento=amount,
            vigente="Sim",
        )
        for oid, day, amount in [
            ("1", "2026-10-02", "12.34"),
            ("2", "2026-11-02", "20.02"),
        ]
    ]
    items = [
        row(
            "Historico_Itens",
            chave="FARMA:" + oid + ":" + iid,
            segmento="FARMA",
            pedido_id=oid,
            item_id=iid,
            sku="0001",
            produto="Synthetic",
            quantidade=quantity,
            valor=amount,
            frete="Não",
            estado="valido",
            vigente="Sim",
        )
        for oid, iid, quantity, amount in [
            ("1", "101", "1", "6.00"),
            ("1", "102", "1", "6.34"),
            ("2", "201", "2", "20.02"),
        ]
    ]
    batch(store, rev, "Historico_Pedidos", history)
    batch(store, rev, "Historico_Itens", items)
    batch(
        store,
        rev,
        "BI_LTV_Clientes",
        [
            row(
                "BI_LTV_Clientes",
                chave="FARMA:synthetic-owner",
                segmento="FARMA",
                cliente_id="synthetic-owner",
                pedidos="2",
                ltv_observado="32.36",
                vigente="Sim",
            )
        ],
    )
    sale = opaque_key("venda", "FARMALIDER:1")
    batch(
        store,
        rev,
        "BI_Itens",
        [
            row(
                "BI_Itens",
                item_chave="operational-" + iid,
                venda_chave=sale,
                produto_codigo="0001",
                quantidade="1",
                receita_item=amount,
                data="2026-10-02",
                sku_informado="1",
            )
            for iid, amount in [("101", "6.00"), ("102", "6.34")]
        ],
    )
    first = finish(store, rev)
    reader = Reader(DSN, "homologacao", "FARMA")
    result = reader.query(
        "BI_Itens", ["item_chave", "valor_unitario"], "2026-01-01", "2026-12-31", [], {}
    )
    keys = {r[0] for r in result["rows"]}
    assert len(keys) == 3 and {"operational-101", "operational-102"} <= keys
    # O item somente histórico não ganha preço unitário/horário inventado.
    assert (
        next(
            r[1]
            for r in result["rows"]
            if r[0] not in ("operational-101", "operational-102")
        )
        is None
    )
    assert reader.query(
        "BI_Itens",
        ["produto_codigo", "quantidade", "receita_item"],
        "2026-01-01",
        "2026-12-31",
        [],
        dict(produto_codigo="count_distinct", quantidade="sum", receita_item="sum"),
    )["rows"] == [[1, "4", "32.36"]]
    customers = reader.query(
        "BI_Clientes",
        ["pedidos_identificados", "faturamento_identificado"],
        "",
        "",
        [],
        {},
    )["rows"]
    assert customers == [["2", "32.36"]]
    # Alterar item sem acertar o pedido bloqueia publicação e preserva o READY anterior.
    revision = begin(store)
    batch(
        store,
        revision,
        "BI_Itens",
        [
            row(
                "BI_Itens",
                item_chave="operational-101",
                venda_chave=sale,
                produto_codigo="0001",
                quantidade="1",
                receita_item="99.00",
                data="2026-10-02",
                sku_informado="1",
            )
        ],
    )
    with pytest.raises(StorageError, match="ITENS_PEDIDO_DIVERGENTE"):
        finish(store, revision)
    assert store.info()["version"] == first["version"]
    store.abort(revision)
    revision = begin(store)
    batch(
        store,
        revision,
        "Historico_Pedidos",
        [
            dict(
                history[0],
                estado="cancelado",
                produtos="0.00",
                frete="0.00",
                faturamento="0.00",
            )
        ],
    )
    batch(
        store,
        revision,
        "BI_LTV_Clientes",
        [
            row(
                "BI_LTV_Clientes",
                chave="FARMA:synthetic-owner",
                segmento="FARMA",
                cliente_id="synthetic-owner",
                pedidos="1",
                ltv_observado="20.02",
                vigente="Sim",
            )
        ],
    )
    finish(store, revision)
    assert reader.query(
        "BI_Itens",
        ["receita_item"],
        "2026-01-01",
        "2026-12-31",
        [],
        dict(receita_item="sum"),
    )["rows"] == [["20.02"]]
    assert reader.query(
        "BI_Clientes",
        ["pedidos_identificados", "faturamento_identificado"],
        "",
        "",
        [],
        {},
    )["rows"] == [["1", "20.02"]]


def test_concurrent_begin_and_identical_batch_are_fenced(store):
    from concurrent.futures import ThreadPoolExecutor

    def attempt(_):
        try:
            return begin(store)
        except StorageError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert results.count("DS_REVISAO_PENDENTE_RETOMAR") == 1
    revision = next(r for r in results if r != "DS_REVISAO_PENDENTE_RETOMAR")
    bid = str(uuid4())
    item = row("BI_Itens", item_chave="synthetic-concurrent")
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(
            pool.map(lambda _: store.batch(revision, bid, "BI_Itens", [item]), [1, 2])
        )
    assert receipts[0] == receipts[1]
    assert len(store.rows("BI_Itens", revision=revision)["rows"]) == 1


def test_real_terminal_prepare_pilot_resume_conference_idempotence_and_rollback(
    store, tmp_path, monkeypatch, capsys
):
    import json
    from contextlib import closing
    from types import SimpleNamespace

    from psycopg.types.json import Jsonb

    import nexo_cli
    import run_datastudio
    from ds_backend.client import Client
    from ds_backend.migration import Export

    token = "synthetic-terminal-token-not-used-elsewhere-12345"
    web = TestClient(create_app(store, token))

    class Session:
        def __init__(self):
            self.headers = {}

        def request(self, method, url, **kwargs):
            return web.request(
                method,
                url.removeprefix("https://test.invalid"),
                json=kwargs["json"],
                headers=self.headers,
            )

        def close(self):
            pass

    config = dict(
        endpoint="https://test.invalid",
        api_token=token,
        access_client_id="synthetic.access",
        access_client_secret="synthetic",
        environment="homologacao",
        segment="FARMA",
        protocol="nexoflow_datastudio_1",
    )
    monkeypatch.setattr(
        Client, "from_settings", lambda _: Client(config, session=Session())
    )
    monkeypatch.setattr(
        run_datastudio, "load_private_settings", lambda: SimpleNamespace()
    )
    monkeypatch.setattr("proxy_config.configure_proxy", lambda: None)
    export = tmp_path / "cut.sqlite"
    plan = tmp_path / "plan.json"
    with closing(Export(export, create=True)) as package:
        # Mais de um lote: o limite deve realmente pausar e retomar.
        for start in (0, 1000):
            package.add(
                "BI_Itens",
                [
                    row(
                        "BI_Itens",
                        item_chave="i-" + str(i),
                        data="2026-11-02",
                        produto_codigo="0001",
                        quantidade="1",
                        receita_item="0.10",
                    )
                    for i in range(start, min(start + 1000, 1001))
                ],
                "FARMA",
            )
        manifest = package.seal(
            "FARMA",
            dict(scope="CORTE_COMPLETO", state="READY", revision="synthetic-ready"),
        )
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO controle.nf_origens VALUES(%s,%s,%s)",
            ("FARMA", digest(manifest), Jsonb(manifest)),
        )

    def command(*args):
        assert nexo_cli.run(["armazenamento", "postgres", *map(str, args)]) == 0

    command("preparar", "--exportacao", export, "--revisao", plan)
    command("simular", "--revisao", plan)
    assert store.rows("BI_Itens")["rows"] == []
    command("aplicar", "--revisao", plan, "--max-lotes", "1")
    revision = json.loads(plan.read_text())["revision"]
    assert json.loads(plan.read_text())["state"] == "PAUSADA"
    assert len(store.rows("BI_Itens", revision=revision)["rows"]) == 1000
    command("retomar", "--revisao", plan)
    assert len(list(Client(config, session=Session()).rows("BI_Itens", None))) == 1001
    command("conferir", "--saida", tmp_path / "conference.json")
    version = json.loads(plan.read_text())["receipt"]["version"]
    with store.connect() as conn:
        count = conn.execute("SELECT count(*) AS n FROM farma.nf_registros").fetchone()[
            "n"
        ]
    command("retomar", "--revisao", plan)
    with store.connect() as conn:
        assert (
            conn.execute("SELECT count(*) AS n FROM farma.nf_registros").fetchone()["n"]
            == count
        )
    command("reverter", "--id-revisao", revision, "--versao", version)
    assert store.rows("BI_Itens")["rows"] == []
    assert "synthetic-terminal-token" not in capsys.readouterr().out


def test_current_projection_date_index_and_stable_work_bound(store):
    from psycopg import sql

    revision = begin(store)
    for start in range(0, 6000, 1000):
        batch(
            store,
            revision,
            "BI_Itens",
            [
                row(
                    "BI_Itens",
                    item_chave=str(i),
                    data="2026-11-02" if i < 12 else "2020-04-20",
                    quantidade="1",
                    receita_item="0.10",
                )
                for i in range(start, start + 1000)
            ],
        )
    finish(store, revision)
    with store.connect() as conn:
        conn.execute("ANALYZE farma.nf_atuais")
        query = sql.SQL(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) SELECT * FROM farma.ds_bi_itens_operacional WHERE data=%s"
        )
        plan = conn.execute(query, ("2026-11-02",)).fetchone()["QUERY PLAN"][0]["Plan"]

        def leaves(node):
            if not node.get("Plans"):
                yield node
            for child in node.get("Plans", []):
                yield from leaves(child)

        scans = list(leaves(plan))
        assert any("Index" in n["Node Type"] for n in scans)
        assert sum(n.get("Rows Removed by Filter", 0) for n in scans) < 50
        assert plan["Actual Rows"] == 12
