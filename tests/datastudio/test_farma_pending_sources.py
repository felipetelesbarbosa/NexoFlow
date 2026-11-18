"""Homologação das projeções FARMA sobre PostgreSQL descartável."""

from datetime import date
from uuid import uuid4

import pytest

from ds_backend.contract import StorageError
from integrations.datastudio.admin import grants, run
from integrations.datastudio.ads_panel_audit import audit
from integrations.datastudio.reader import Reader
from integrations.datastudio.weni_daily import TABLE, put
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, batch, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(
    not DSN, reason="PostgreSQL descartável não configurado"
)


def cli(store, tmp_path, *args):
    file = tmp_path / "dsn"
    file.write_text(store.dsn, encoding="utf-8")
    return run(
        [
            "--dsn-file",
            str(file),
            "--ambiente",
            "homologacao",
            "--segmento",
            "FARMA",
            *args,
        ]
    )


def test_public_summary_collapses_volume_and_preserves_joint_filters(store, tmp_path):
    rev = begin(store)
    with store.connect() as conn:
        grants(conn, "FARMA")
    finish(store, rev)
    reader = Reader(DSN, "homologacao", "FARMA")
    table = "BI_Publico_Resumo"
    fields = ["contatos", "compra_identificada", "sem_compra_identificada"]
    with pytest.raises(StorageError, match="DS_PUBLICO_VISAO_AUSENTE"):
        reader.query(table, fields, "", "", [], {})
    with pytest.raises(StorageError, match="DS_REVISAO_AUSENTE"):
        cli(store, tmp_path, "--instalar-publico-farma", str(uuid4()))
    assert cli(store, tmp_path, "--instalar-publico-farma", rev) == 1
    assert cli(store, tmp_path, "--instalar-publico-farma", rev) == 1
    assert reader.query(table, fields, "", "", [], {})["rows"] == []

    # Reproduz o volume do transporte. IDs e valores individuais são fictícios.
    with store.connect() as conn:
        conn.execute("""
            INSERT INTO farma.nf_atuais(tabela,chave,registro)
            SELECT 'BI_Publico', i::text, jsonb_build_object(
              'contato_chave',i, 'nome','fixture privada', 'cliente_chave','mesmo cliente',
              'cidade',CASE WHEN i%3=0 THEN 'Belém' WHEN i%3=1 THEN 'Ananindeua' ELSE '' END,
              'canal',CASE WHEN i%2=0 THEN 'whatsapp' ELSE 'outro' END,
              'idade',CASE WHEN i%5=0 THEN '' ELSE (18 + i%47)::text END,
              'idade_informada', CASE WHEN i%5=0 THEN 0 ELSE 1 END,
              'compra_identificada', CASE WHEN i<=30939 THEN 1 ELSE 0 END)
            FROM generate_series(1,48843) i
            """)
    with store.connect(readonly=True) as conn:
        conn.execute("SET LOCAL ROLE nf_ds_farma_read")
        assert (
            conn.execute(
                "SELECT count(*) AS grupos FROM farma.ds_bi_publico_resumo"
            ).fetchone()["grupos"]
            == 288
        )
        control = conn.execute("""
            SELECT count(*) AS n,sum(compra_identificada) AS compras
            FROM farma.ds_bi_publico WHERE cidade='Belém' AND canal='whatsapp'
            AND idade=25 AND idade_informada=1
            """).fetchone()

    response = reader.query(table, fields, "", "", [], {})
    assert response["complete"]
    assert len(response["rows"]) == 288
    assert [sum(values) for values in zip(*response["rows"], strict=True)] == [
        48843,
        30939,
        17904,
    ]
    filters = [
        dict(field=k, values=[v])
        for k, v in (
            ("cidade", "Belém"),
            ("canal", "whatsapp"),
            ("idade", 25),
            ("idade_informada", 1),
        )
    ]
    assert reader.query(table, fields, "", "", filters, {})["rows"] == [
        [control["n"], int(control["compras"]), control["n"] - int(control["compras"])]
    ]
    with pytest.raises(StorageError, match="DS_CAMPOS_NAO_AUTORIZADOS"):
        reader.query(table, ["contato_chave", "nome"], "", "", [], {})
    with pytest.raises(StorageError, match="DS_PUBLICO_AGREGACAO_INVALIDA"):
        reader.query(table, fields, "", "", [], {"contatos": "count"})
    with pytest.raises(StorageError, match="DS_TABELA_NAO_AUTORIZADA"):
        Reader(DSN, "homologacao", "PET").query(table, fields, "", "", [], {})
    assert store.inspect(rev)["state"] == "READY"


def test_public_summary_matches_looker_formula_for_missing_fields(store, tmp_path):
    with store.connect() as conn:
        grants(conn, "FARMA")
    rev = begin(store)
    batch(
        store,
        rev,
        "BI_Publico",
        [
            row("BI_Publico", contato_chave="a", cidade="", compra_identificada=""),
            row("BI_Publico", contato_chave="b", cidade="   ", compra_identificada=0),
            row(
                "BI_Publico",
                contato_chave="c",
                cidade="Não informado",
                compra_identificada=1,
            ),
            row("BI_Publico", contato_chave="d", cidade="Belém", compra_identificada=0),
        ],
    )
    finish(store, rev)

    # Simula uma cópia que já instalou a visão do commit anterior. Os tipos
    # permanecem os mesmos para CREATE OR REPLACE VIEW atualizar a definição.
    with store.connect() as conn:
        conn.execute("""
            CREATE VIEW farma.ds_bi_publico_resumo AS
            SELECT cidade,canal,idade,idade_informada,0::bigint AS contatos,
              0::bigint AS compra_identificada,0::bigint AS sem_compra_identificada,
              0::bigint AS contatos_idade_informada,0::bigint AS contatos_sem_cidade
            FROM farma.ds_bi_publico WHERE false
            """)
    cli(store, tmp_path, "--instalar-publico-farma", rev)
    reader = Reader(DSN, "homologacao", "FARMA")
    fields = [
        "cidade",
        "contatos",
        "compra_identificada",
        "sem_compra_identificada",
        "contatos_sem_cidade",
    ]
    result = reader.query("BI_Publico_Resumo", fields, "", "", [], {})
    assert {city: counts for city, *counts in result["rows"]} == {
        None: [2, 0, 2, 2],
        "Não informado": [1, 1, 0, 1],
        "Belém": [1, 0, 1, 0],
    }


def test_ads_panel_delta_by_id_distinguishes_origin_scope_and_money(store):
    rev = begin(store)

    def bi(key, ad, classification, currency, cost, meta, weni):
        return row(
            "BI_Meta_Resultados",
            chave=key,
            segmento="FARMA",
            anuncio_id=ad,
            conta_id="01",
            data="2026-11-02",
            classificacao=classification,
            moeda=currency,
            investimento_atribuivel=cost,
            conversas_iniciadas_meta=meta,
            conversas=weni,
        )

    batch(
        store,
        rev,
        "BI_Meta_Resultados",
        [
            bi("a", "001", "FARMA", "BRL", "2.03", "7", "1"),
            bi("b", "002", "FARMA", "BRL", "3.14", "3", "2"),
            bi("c", "003", "FARMA", "BRL", "22.35", "8", ""),
            bi("d", "004", "NAO_CLASSIFICADO", "BRL", "", "900", ""),
            bi("e", "005", "FARMA", "USD", "99", "600", ""),
        ],
    )
    batch(
        store,
        rev,
        "Meta_Ads_Diario",
        [
            row(
                "Meta_Ads_Diario",
                chave="c",
                segmento="FARMA",
                conta_id="01",
                anuncio_id="003",
                data="2026-11-02",
                campanha_id="0003",
                campanha_nome="teste",
                anuncio_status="PAUSED",
            ),
        ],
    )
    finish(store, rev)

    start, end = date(2026, 11, 1), date(2026, 11, 18)
    copy = [
        dict(anuncio_id="001", investimento_centavos=203, conversas_meta=7),
        dict(anuncio_id="002", investimento_centavos=314, conversas_meta=3),
    ]
    result = audit(store, rev, start, end, copy)
    assert result["versao"] == 1
    assert [item["presenca"] for item in result["conciliacao"]] == [
        "AMBOS",
        "AMBOS",
        "SO_POSTGRESQL",
    ]
    assert result["conciliacao"][-1] == {
        "anuncio_id": "003",
        "presenca": "SO_POSTGRESQL",
        "investimento_centavos_delta_pg_menos_copia": 2235,
        "conversas_meta_delta_pg_menos_copia": 8,
    }
    assert result["linhas_por_anuncio"][2]["conversas_weni"] is None
    assert result["linhas_por_anuncio"][2]["campanhas"] == ["0003"]
    assert result["linhas_por_anuncio"][2]["estados"] == ["PAUSED"]
    with pytest.raises(StorageError, match="DS_ANUNCIOS_COPIA_INVALIDA"):
        audit(store, rev, start, end, copy * 2)
    with pytest.raises(StorageError, match="DS_REVISAO_AUSENTE"):
        audit(store, str(uuid4()), start, end)


def test_install_weni_missing_view_replay_and_coverage_on_ready(store, tmp_path):
    with store.connect() as conn:
        grants(conn, "FARMA")
    rev = begin(store)
    finish(store, rev)
    reader = Reader(DSN, "homologacao", "FARMA")
    fields = ["conversas_weni", "resolvidas", "nao_resolvidas", "transferidas"]
    aggregation = dict.fromkeys(fields, "sum")
    start, end = "2026-11-01", "2026-11-06"

    def read():
        return reader.query(TABLE, fields, start, end, [], aggregation)

    with pytest.raises(StorageError, match="DS_INSIGHTS_VISAO_AUSENTE"):
        read()
    project = str(uuid4())
    install_args = ("--instalar-conversas-projeto", project)
    cli(store, tmp_path, *install_args)
    with pytest.raises(StorageError, match="DS_INSIGHTS_COBERTURA_INCOMPLETA"):
        read()

    sample = [
        (158, 98, 60, 0),
        (252, 66, 29, 157),
        (408, 77, 54, 277),
        (381, 81, 42, 258),
        (424, 83, 86, 255),
        (379, 60, 45, 274),
    ]

    def publish():
        return [
            put(
                store,
                project,
                f"2026-11-{day:02}",
                "2026-11-08T12:00:00+00:00",
                dict(zip(fields, metrics, strict=True)),
                "WENI_FLOWS_V2",
            )
            for day, metrics in enumerate(sample, start=1)
        ]

    receipts = publish()
    cli(store, tmp_path, *install_args)
    assert publish() == receipts
    assert read()["rows"] == [[2002, 465, 316, 1221]]
    assert read()["version"] == 1
    with store.connect(readonly=True) as conn:
        conn.execute("SET LOCAL ROLE nf_ds_farma_read")
        item = conn.execute("""
            SELECT count(*) AS n, count(DISTINCT data) AS dias,
                   array_agg(DISTINCT origem) AS origem, array_agg(DISTINCT fuso) AS fuso
            FROM farma.ds_bi_weni_conversas_diarias
            """).fetchone()
    assert item == dict(n=6, dias=6, origem=["WENI_FLOWS_V2"], fuso=["America/Belem"])
    assert store.inspect(rev)["state"] == "READY"

    # Mesmo número de linhas que o período, com um dia faltando e outro repetido.
    # Uma visão divergente precisa bloquear o resultado, independentemente da PK.
    with store.connect() as conn:
        conn.execute("""
            CREATE OR REPLACE VIEW farma.ds_bi_weni_conversas_diarias AS
            SELECT CASE WHEN data='2026-11-06' THEN '2026-11-05'::date ELSE data END AS data,
                   'FARMA'::text AS segmento,conversas_weni,resolvidas,nao_resolvidas,transferidas,
                   origem,'America/Belem'::text AS fuso FROM farma.nf_weni_dias
            """)
    with pytest.raises(StorageError, match="DS_INSIGHTS_COBERTURA_INCOMPLETA"):
        read()
    cli(store, tmp_path, *install_args)
    assert read()["rows"] == [[2002, 465, 316, 1221]]
