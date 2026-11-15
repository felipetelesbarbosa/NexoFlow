"""Volume sintético, paridade com o núcleo oficial e snapshot READY consistente."""

import json
import subprocess
from decimal import Decimal

import pytest
from psycopg.types.json import Jsonb

from ds_backend.contract import StorageError, record_key
from integrations.datastudio.reader import Reader
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")


def seed(store, n=60003):
    """Carga COPY somente no banco descartável já conferido pela fixture."""
    rev = begin(store)
    finish(store, rev)
    items, orders = [], []
    for number in range(n):
        sale = "s" + str(number // 3)
        day = "2026-11-01" if number % 6 < 3 else "2026-11-02"
        items.append(
            row(
                "BI_Itens",
                item_chave="i" + str(number),
                venda_chave=sale,
                data=day,
                produto_codigo="001" if number % 3 < 2 else "002",
                produto_nome="A" if number % 3 < 2 else "B",
                categoria="Cat",
                quantidade="1",
                receita_item="0.10",
                sku_informado="1",
            )
        )
        if number % 3 == 0:
            orders.append(
                row(
                    "BI_Clientes_Vendas",
                    venda_chave=sale,
                    data=day,
                    faturamento_produtos="0.30",
                    frete="99.00",
                    faturamento="99.30",
                )
            )
    with store.connect() as conn:
        with conn.cursor().copy(
            "COPY farma.nf_atuais(tabela,chave,registro) FROM STDIN"
        ) as copy:
            for table, rows, _key in [
                ("BI_Itens", items, "item_chave"),
                ("BI_Clientes_Vendas", orders, "venda_chave"),
            ]:
                for r in rows:
                    copy.write_row((table, record_key(table, r), Jsonb(r)))
    return items, orders


def test_abc_over_50k_raw_refused_aggregated_complete(store):
    seed(store)
    reader = Reader(DSN, "homologacao", "FARMA")
    with pytest.raises(StorageError, match="EXCEDE_LIMITE"):
        reader.query("BI_Itens", ["item_chave"], "2026-01-01", "2026-11-15", [], {})
    r = reader.abc(
        "abc",
        ["produto_codigo", "unidades", "receita_produtos", "pedidos"],
        "2026-01-01",
        "2026-11-15",
    )
    assert r["complete"] and r["version"] == 1
    assert r["rows"] == [
        ["001", 40002, "4000.2", 20001],
        ["002", 20001, "2000.1", 20001],
    ]
    pair = reader.abc(
        "juntos",
        ["produto_a_codigo", "produto_b_codigo", "pedidos_juntos"],
        "2026-01-01",
        "2026-11-15",
    )
    assert pair["rows"] == [["001", "002", 20001]]
    summary = reader.abc(
        "resumo", ["skus_distintos", "faturamento_produtos"], "2026-01-01", "2026-11-15"
    )
    assert summary["rows"][0][0] == 2
    assert Decimal(summary["rows"][0][1]) == Decimal("6000.30")
    # Mesmo o número de SKUs pode exceder 50 mil: o resumo SQL continua completo.
    with store.connect() as conn:
        conn.execute("""UPDATE farma.nf_atuais
          SET registro=registro||jsonb_build_object('produto_codigo',registro->>'item_chave')
          WHERE tabela='BI_Itens'""")
    summary = reader.abc(
        "resumo", ["skus_distintos", "faturamento_produtos"], "2026-01-01", "2026-11-15"
    )
    assert summary["rows"][0][0] == 60003
    assert Decimal(summary["rows"][0][1]) == Decimal("6000.30")
    with pytest.raises(StorageError, match="EXCEDE_LIMITE"):
        reader.abc("abc", ["produto_codigo"], "2026-01-01", "2026-11-15")
    with pytest.raises(StorageError, match="EXCEDE_LIMITE"):
        reader.abc("juntos", ["pedidos_juntos"], "2026-01-01", "2026-11-15")


def legacy(items, orders, start, end):
    item_fields = "item_chave venda_chave data produto_codigo produto_nome categoria quantidade receita_item atualizado_em".split()
    order_fields = "venda_chave data faturamento_produtos atualizado_em".split()

    def matrix(records, fields):
        return [fields] + [
            [r.get(f, "") if f != "atualizado_em" else "READY:1" for f in fields]
            for r in records
        ]

    return json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "const fs=require('fs'),core=require('./connectors/looker_abc/AbcCore.js'); const p=JSON.parse(fs.readFileSync(0,'utf8')); console.log(JSON.stringify(core.calculate(...p)));",
            ],
            input=json.dumps(
                [matrix(items, item_fields), matrix(orders, order_fields), start, end]
            ),
            text=True,
        )
    )


def comparable(value):
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    return value


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-11-01", "2026-11-01"),
        ("2026-11-01", "2026-11-02"),
        ("2026-11-30", "2026-11-30"),
    ],
)
def test_server_matches_original_core_every_field(store, start, end):
    from integrations.datastudio.abc_reader import FIELDS

    items, orders = seed(store, 60)
    expected = legacy(items, orders, start, end)
    reader = Reader(DSN, "homologacao", "FARMA")
    for mode, fields in FIELDS.items():
        response = reader.abc(mode, fields, start, end)
        assert len(response["rows"]) == len(expected[mode])
        for got, want in zip(response["rows"], expected[mode], strict=True):
            for key, value in zip(fields, got, strict=True):
                if key == "atualizado_em":
                    assert value == ""
                elif isinstance(want[key], (int, float)):
                    assert float(value) == pytest.approx(want[key], abs=1e-12)
                else:
                    assert value == want[key]
    assert response["version"] == 1


def test_abc_missing_sku_ties_latest_name_matches_core(store):
    from integrations.datastudio.abc_reader import FIELDS

    items, orders = seed(store, 6)
    items[0]["produto_codigo"] = ""
    items[4]["produto_nome"] = "Z updated"
    with store.connect() as conn:
        for item in items:
            conn.execute(
                "UPDATE farma.nf_atuais SET registro=%s WHERE tabela=%s AND chave=%s",
                (Jsonb(item), "BI_Itens", record_key("BI_Itens", item)),
            )
    expected = legacy(items, orders, "2026-11-01", "2026-11-02")
    reader = Reader(DSN, "homologacao", "FARMA")
    for mode in FIELDS:
        fields = FIELDS[mode]
        got = reader.abc(mode, fields, "2026-11-01", "2026-11-02")["rows"]
        for actual, want in zip(got, expected[mode], strict=True):
            for key, v in zip(fields, actual, strict=True):
                if key == "atualizado_em":
                    assert v == ""
                elif isinstance(want[key], (int, float)):
                    assert float(v) == pytest.approx(want[key])
                else:
                    assert v == want[key]


@pytest.mark.parametrize(
    "problem", ["amount", "missing_order", "date", "quantity", "duplicate"]
)
def test_inconsistent_base_fails_instead_of_empty_or_partial(store, problem):
    seed(store, 6)
    with store.connect() as conn:
        if problem == "missing_order":
            conn.execute(
                "DELETE FROM farma.nf_atuais WHERE tabela='BI_Clientes_Vendas' AND registro->>'venda_chave'='s0'"
            )
        elif problem == "duplicate":
            conn.execute(
                "INSERT INTO farma.nf_atuais SELECT tabela,'duplicate',registro||'{\"receita_item\":\"0.11\"}'::jsonb FROM farma.nf_atuais WHERE tabela='BI_Itens' AND registro->>'item_chave'='i0'"
            )
        else:
            update = {
                "amount": {"receita_item": "1"},
                "date": {"data": "2026-11-02"},
                "quantity": {"quantidade": "0"},
            }[problem]
            conn.execute(
                "UPDATE farma.nf_atuais SET registro=registro||%s WHERE tabela='BI_Itens' AND registro->>'item_chave'='i0'",
                (Jsonb(update),),
            )
    reader = Reader(DSN, "homologacao", "FARMA")
    for mode in ("abc", "resumo", "juntos"):
        with pytest.raises(StorageError, match="DS_ABC_BASE_INCOMPLETA"):
            reader.abc(mode, ["periodo_inicio"], "2026-11-01", "2026-11-02")


def test_abc_version_change_reads_one_complete_ready_snapshot(store, monkeypatch):
    from tests.datastudio.test_ds_database import batch

    items, _ = seed(store, 6)
    rev = begin(store)
    batch(store, rev, "BI_Itens", [dict(items[0], produto_codigo="003")])
    reader = Reader(DSN, "homologacao", "FARMA")
    original = reader.active

    def active(conn):
        version = original(conn)
        finish(store, rev)
        return version

    monkeypatch.setattr(reader, "active", active)
    old = reader.abc("resumo", ["skus_distintos"], "2026-11-01", "2026-11-02")
    assert old["version"] == 1 and old["rows"] == [[2]]
    monkeypatch.setattr(reader, "active", original)
    new = reader.abc("resumo", ["skus_distintos"], "2026-11-01", "2026-11-02")
    assert new["version"] == 2 and new["rows"] == [[3]]
    pet = Reader(DSN, "homologacao", "PET")
    with pytest.raises(StorageError, match="SEM_PUBLICACAO"):
        pet.abc("abc", ["produto_codigo"], "2026-11-01", "2026-11-02")


def test_abc_endpoint_permissions_no_write_and_no_partial_limit(store, monkeypatch):
    from fastapi.testclient import TestClient

    from integrations.datastudio.abc_reader import FIELDS
    from integrations.datastudio.admin import grants
    from integrations.datastudio.api import create_app

    seed(store, 6)
    with store.connect() as conn:
        grants(conn, "FARMA")
        conn.execute("ALTER ROLE nf_ds_farma_read LOGIN PASSWORD 'synthetic-abc-only'")
    import psycopg

    config = psycopg.conninfo.conninfo_to_dict(DSN)
    config.update(user="nf_ds_farma_read", password="synthetic-abc-only")
    reader = Reader(
        psycopg.conninfo.make_conninfo(**config),
        "homologacao",
        "FARMA",
        require_dedicated_role=True,
    )
    client = TestClient(create_app(reader, "x" * 32, reader=True))
    payload = dict(
        mode="abc", fields=FIELDS["abc"], start="2026-11-01", end="2026-11-02"
    )
    assert client.post("/v1/abc", json=payload).status_code == 401
    headers = {"Authorization": "Bearer " + "x" * 32}
    response = client.post("/v1/abc", json=payload, headers=headers)
    assert response.status_code == 200 and len(response.json()["rows"]) == 2
    assert client.post("/v1/lotes", json={}, headers=headers).status_code == 404
    monkeypatch.setattr("integrations.datastudio.reader.MAX_RESULT_ROWS", 1)
    response = client.post("/v1/abc", json=payload, headers=headers)
    assert response.status_code == 409 and "rows" not in response.json()


def test_abc_cancellations_exclusions_and_freight_stay_in_financial_views(store):
    from looker_bi import opaque_key
    from tests.datastudio.test_ds_database import batch

    rev = begin(store)
    # Apenas uma venda elegível: produtos 10.10, frete 5.00 (nunca unidades).
    for order_id, state, current, excluded in [
        ("good", "valido", "Sim", False),
        ("cancelled", "cancelado", "Sim", False),
        ("excluded", "valido", "Sim", True),
        ("old", "valido", "Não", False),
    ]:
        sale = opaque_key("venda", "FARMALIDER:" + order_id)
        batch(
            store,
            rev,
            "Historico_Pedidos",
            [
                row(
                    "Historico_Pedidos",
                    chave="FARMA:" + order_id,
                    segmento="FARMA",
                    pedido_id=order_id,
                    cliente_id="owner",
                    data="2026-11-02",
                    estado=state,
                    vigente=current,
                    produtos="10.10",
                    frete="5.00",
                    faturamento="15.10",
                )
            ],
        )
        batch(
            store,
            rev,
            "Historico_Itens",
            [
                row(
                    "Historico_Itens",
                    chave="FARMA:" + order_id + ":" + str(i),
                    segmento="FARMA",
                    pedido_id=order_id,
                    item_id=str(i),
                    sku="001",
                    produto="Synthetic",
                    quantidade="1",
                    valor=amount,
                    frete=freight,
                    estado=state,
                    vigente=current,
                )
                for i, amount, freight in [(1, "10.10", "Não"), (2, "5.00", "Sim")]
            ],
        )
        # Operacional cancelado/excluído também não pode entrar na ABC.
        batch(
            store,
            rev,
            "BI_Itens",
            [
                row(
                    "BI_Itens",
                    item_chave="op-" + order_id,
                    venda_chave=sale,
                    data="2026-11-02",
                    produto_codigo="001",
                    produto_nome="Synthetic",
                    quantidade="1",
                    receita_item="10.10",
                    sku_informado="1",
                )
            ],
        )
        if excluded:
            batch(
                store,
                rev,
                "Exclusoes_Publicacao",
                [row("Exclusoes_Publicacao", pedido_id=order_id, segmento="FARMA")],
            )
    # Fixture isolada: projeção inclui fatos excluídos conservados para testar a
    # leitura; não usar finish para produzir um READY comercial artificial.
    with store.connect() as conn:
        conn.execute(
            "INSERT INTO farma.nf_atuais SELECT tabela,chave,registro FROM farma.nf_stage WHERE execucao=%s",
            (rev,),
        )
        conn.execute(
            "UPDATE controle.nf_publicacoes SET versao=1 WHERE segmento='FARMA'"
        )
    reader = Reader(DSN, "homologacao", "FARMA")
    result = reader.abc(
        "abc",
        ["produto_codigo", "unidades", "receita_produtos", "pedidos"],
        "2026-11-01",
        "2026-11-03",
    )
    assert result["rows"] == [["001", 1, "10.1", 1]]
    with store.connect() as conn:
        assert (
            conn.execute(
                "SELECT count(*) AS n FROM farma.nf_atuais WHERE tabela='Historico_Itens'"
            ).fetchone()["n"]
            == 8
        )
        assert (
            conn.execute(
                "SELECT estado FROM controle.nf_execucoes WHERE id=%s", (rev,)
            ).fetchone()["estado"]
            == "WRITING"
        )


def test_abc_timeout_is_explicit_not_empty(store, monkeypatch):
    import psycopg
    from fastapi.testclient import TestClient

    from integrations.datastudio.api import create_app

    seed(store, 3)

    def fail(*args):
        raise psycopg.errors.QueryCanceled("private SQL must not leak")

    monkeypatch.setattr("integrations.datastudio.abc_reader.aggregates", fail)
    reader = Reader(DSN, "homologacao", "FARMA")
    client = TestClient(create_app(reader, "x" * 32, reader=True))
    r = client.post(
        "/v1/abc",
        headers={"Authorization": "Bearer " + "x" * 32},
        json=dict(
            mode="resumo",
            fields=["faturamento_produtos"],
            start="2026-11-01",
            end="2026-11-02",
        ),
    )
    assert r.status_code == 409
    assert r.json() == {"error": "DS_CONSULTA_TEMPO_LIMITE"}


def test_other_long_sources_use_explicit_sql_aggregates_without_changing_grain(store):
    # >50k fatos em cada fonte; repetir cliente/dia não duplica o DISTINCT.
    from integrations.datastudio.read_catalog import READ_REGISTRY

    seed(store, 3)
    count = 50004
    tables = {
        "BI_Clientes_Vendas": (
            dict(
                venda_chave="s",
                cliente_chave="same",
                data="2026-11-02",
                pedidos="1",
                faturamento_produtos="0.10",
                frete="0.01",
                faturamento="0.11",
            ),
            "venda_chave",
            ["cliente_chave", "faturamento"],
            {"cliente_chave": "count_distinct", "faturamento": "sum"},
            [1, "5500.44"],
        ),
        "Itens_Pedidos_FarmaLider": (
            dict(
                item_chave="i",
                pedido_chave="same",
                data="2026-11-02",
                produto_codigo="001",
                quantidade="1",
                valor_total="0.10",
            ),
            "item_chave",
            ["produto_codigo", "quantidade", "valor_total"],
            {"quantidade": "sum", "valor_total": "sum"},
            ["001", "50004", "5000.40"],
        ),
        "Metricas_Diarias": (
            dict(
                data="2026-11-02",
                tipo_atribuicao="primeiro",
                anuncio_id="a",
                anuncio_titulo="Synthetic",
                contatos="1",
            ),
            "anuncio_id",
            ["tipo_atribuicao", "contatos"],
            {"contatos": "sum"},
            ["primeiro", "50004"],
        ),
    }
    with store.connect() as conn:
        conn.execute("DELETE FROM farma.nf_atuais WHERE tabela='BI_Clientes_Vendas'")
        with conn.cursor().copy(
            "COPY farma.nf_atuais(tabela,chave,registro) FROM STDIN"
        ) as copy:
            for name, (values, key, _, _, _) in tables.items():
                for i in range(count):
                    r = row(name, **dict(values, **{key: str(i)}))
                    copy.write_row((name, record_key(name, r), Jsonb(r)))
    reader = Reader(DSN, "homologacao", "FARMA")
    for name, (_, _, fields, aggregation, expected) in tables.items():
        spec = READ_REGISTRY[name]
        assert spec["public"]
        got = reader.query(name, fields, "2026-01-01", "2026-11-15", [], aggregation)
        assert got["complete"] and got["version"] == 1
        assert got["rows"] == [expected]


@pytest.mark.parametrize(
    "revenues", [[80, 15, 5], [80, 10, 10], [40, 40, 15, 5], [0, 0], [95, 3, 2]]
)
def test_sql_summary_class_boundaries_match_core(store, revenues):
    from integrations.datastudio.abc_reader import FIELDS

    items, orders = seed(store, len(revenues) * 3)
    for i, item in enumerate(items):
        item.update(produto_codigo=str(i // 3), receita_item=str(revenues[i // 3]))
    for i, order in enumerate(orders):
        order["faturamento_produtos"] = str(revenues[i] * 3)
    with store.connect() as conn:
        for name, records in [("BI_Itens", items), ("BI_Clientes_Vendas", orders)]:
            for r in records:
                conn.execute(
                    "UPDATE farma.nf_atuais SET registro=%s WHERE tabela=%s AND chave=%s",
                    (Jsonb(r), name, record_key(name, r)),
                )
    expected = legacy(items, orders, "2026-11-01", "2026-11-02")["resumo"][0]
    fields = FIELDS["resumo"]
    result = Reader(DSN, "homologacao", "FARMA").abc(
        "resumo", fields, "2026-11-01", "2026-11-02"
    )["rows"][0]
    for key, value in zip(fields, result, strict=True):
        if key == "atualizado_em":
            assert value == ""
        elif isinstance(expected[key], (int, float)):
            assert float(value) == pytest.approx(expected[key], abs=1e-12)
        else:
            assert value == expected[key]
