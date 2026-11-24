"""Resumo diário e cabeçalhos do relatório sobre a mesma revisão sintética."""

from decimal import Decimal

import pytest

from ds_backend.contract import StorageError
from integrations.datastudio.reader import Reader, create_views
from looker_bi import opaque_key
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, batch, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")
DAY = "2026-04-11"
NEXT = "2026-04-12"
EMPTY = "2026-04-13"


@pytest.fixture
def published(store):
    rev = begin(store)
    owner = opaque_key("farmalider", "sintetico")
    orders, sales, items = [], [], []
    # 501 teve correção histórica. 502 existe apenas no operacional. 503 foi
    # excluído e 504 foi cancelado. 505 é outra compra do cliente de 501 no mesmo dia.
    for oid, day, products, freight in [
        ("501", DAY, "60.00", "8.00"),
        ("502", NEXT, "12.11", "1.03"),
        ("503", DAY, "9999.34", "20.00"),
        ("504", DAY, "10.00", "4.00"),
        ("505", DAY, "5.00", "1.21"),
    ]:
        total = str(Decimal(products) + Decimal(freight))
        key = "FARMALIDER:" + oid
        sale = opaque_key("venda", key)
        orders.append(
            row(
                "BI_Pedidos",
                pedido_chave=key,
                pedido_id=oid,
                cliente_chave=owner,
                cliente="Comprador sintético",
                data=day,
                venda_valida="1",
                pedido_valor_produtos=products,
                pedido_frete=freight,
                pedido_valor=total,
                pedido_faturamento_total=total,
            )
        )
        sales.append(
            row(
                "BI_Clientes_Vendas",
                venda_chave=sale,
                cliente_chave=owner,
                data=day,
                pedidos="1",
                faturamento_produtos=products,
                frete=freight,
                faturamento=total,
            )
        )
        items.append(
            row(
                "BI_Itens",
                item_chave=oid,
                venda_chave=sale,
                cliente_chave=owner,
                data=day,
                produto_codigo="007",
                quantidade="1",
                receita_item=products,
                sku_informado="1",
            )
        )
    # A chave oficial ainda identifica 502 mesmo sem o campo. A exclusão 503
    # deve barrar também a linha em que o campo diverge dessa chave.
    orders[1]["pedido_id"] = ""
    orders[2]["pedido_id"] = "999"
    orders.append(dict(orders[0], pedido_chave="vinculo-legado"))
    orders.append(
        dict(
            orders[0],
            pedido_chave="outro-contato",
            cliente_chave="outro",
            cliente="Outro comprador",
        )
    )
    orders.extend(
        row("BI_Pedidos", pedido_chave=key, venda_valida="0", data=NEXT)
        for key in ("sem-id-1", "sem-id-2")
    )
    batch(store, rev, "BI_Pedidos", orders)
    batch(store, rev, "BI_Clientes_Vendas", sales)
    batch(store, rev, "BI_Itens", items)
    batch(
        store,
        rev,
        "Exclusoes_Publicacao",
        [row("Exclusoes_Publicacao", segmento="FARMA", pedido_id="503")],
    )
    batch(
        store,
        rev,
        "Historico_Pedidos",
        [
            row(
                "Historico_Pedidos",
                chave="FARMA:" + oid,
                pedido_id=oid,
                segmento="FARMA",
                cliente_id="sintetico",
                data=DAY,
                vigente="Sim",
                estado=state,
                produtos=products,
                frete=freight,
                faturamento=total,
            )
            for oid, state, products, freight, total in [
                ("501", "valido", "67.90", "9.99", "77.89"),
                ("504", "cancelado", "0", "0", "0"),
            ]
        ],
    )
    batch(
        store,
        rev,
        "Historico_Itens",
        [
            row(
                "Historico_Itens",
                chave="FARMA:501:" + key,
                pedido_id="501",
                item_id=key,
                segmento="FARMA",
                sku=sku,
                quantidade=qty,
                valor=value,
                vigente="Sim",
                estado="valido",
                frete=fee,
            )
            for key, sku, qty, value, fee in [
                ("1", "007", "2", "60.00", "Não"),
                ("2", "008", "1", "7.90", "Não"),
                ("3", "0", "1", "9.99", "Sim"),
            ]
        ],
    )
    batch(
        store,
        rev,
        "BI_LTV_Clientes",
        [
            row(
                "BI_LTV_Clientes",
                chave="FARMA:sintetico",
                segmento="FARMA",
                cliente_id="sintetico",
                ltv_observado="77.89",
                pedidos="1",
                vigente="Sim",
            )
        ],
    )
    batch(
        store,
        rev,
        "BI_Vendas",
        [
            row(
                "BI_Vendas",
                data=DAY,
                pedidos="4",
                pedidos_confirmados_api="4",
                clientes_compradores="2",
                faturamento="10101.34",
                faturamento_confirmado_api="10101.34",
                ticket_medio="2525.34",
                taxa_confirmacao_pct="100",
                faturamento_produtos="10069.34",
                faturamento_frete="32.00",
                faturamento_total="10101.34",
                unidades_vendidas="4",
            ),
            row(
                "BI_Vendas",
                data=EMPTY,
                pedidos="0",
                pedidos_confirmados_api="0",
                clientes_compradores="0",
                faturamento="0",
                faturamento_confirmado_api="0",
                ticket_medio="0",
                taxa_confirmacao_pct="0",
                faturamento_produtos="0",
                faturamento_frete="0",
                faturamento_total="0",
                unidades_vendidas="0",
            ),
        ],
    )
    receipt = finish(store, rev)
    with store.connect() as conn:
        create_views(conn)
    assert store.inspect(rev)["receipt"] == receipt
    return Reader(DSN, "homologacao", "FARMA")


def test_official_order_count_and_sum_after_legacy_alias(published):
    result = published.query(
        "BI_Pedidos",
        [
            "pedido_id",
            "pedido_chave",
            "cliente",
            "pedido_valor_produtos",
            "pedido_frete",
            "pedido_faturamento_total",
        ],
        DAY,
        NEXT,
        [{"field": "venda_valida", "values": ["1"]}],
        {},
    )
    assert sorted(result["rows"]) == [
        ["501", "FARMALIDER:501", "Comprador sintético", "67.90", "9.99", "77.89"],
        ["502", "FARMALIDER:502", "Comprador sintético", "12.11", "1.03", "13.14"],
        ["505", "FARMALIDER:505", "Comprador sintético", "5.00", "1.21", "6.21"],
    ]


def test_unidentified_orders_keep_separate_keys(published):
    result = published.query(
        "BI_Pedidos",
        ["pedido_chave"],
        NEXT,
        NEXT,
        [{"field": "venda_valida", "values": ["0"]}],
        {},
    )
    assert sorted(result["rows"]) == [["sem-id-1"], ["sem-id-2"]]


def test_customer_revenue_sums_only_valid_sales_in_period_and_returns_confirmed_zero(published):
    owner = opaque_key("farmalider", "sintetico")
    filters = [{"field": "cliente_chave", "values": [owner]}]
    for start, end, expected in ((DAY, NEXT, "97.24"), (EMPTY, EMPTY, "0")):
        result = published.query(
            "BI_Clientes_Vendas", ["faturamento"], start, end, filters,
            {"faturamento": "sum"},
        )
        assert result["complete"] is True
        assert Decimal(result["rows"][0][0]) == Decimal(expected)


def test_sales_by_day_reconciles_with_items_abc_and_observed_ltv(published):
    fields = [
        "data",
        "pedidos",
        "pedidos_confirmados_api",
        "clientes_compradores",
        "unidades_vendidas",
        "faturamento_produtos",
        "faturamento_frete",
        "faturamento_total",
        "faturamento",
        "faturamento_confirmado_api",
        "ticket_medio",
        "taxa_confirmacao_pct",
    ]
    daily = published.query("BI_Vendas", fields, DAY, EMPTY, [], {})
    actual = sorted((day, *map(Decimal, metrics)) for day, *metrics in daily["rows"])
    expected = [
        (DAY, 2, 2, 1, 4, "72.90", "11.20", "84.10", "84.10", "84.10", "42.05", 100),
        (NEXT, 1, 1, 1, 1, "12.11", "1.03", "13.14", "13.14", "13.14", "13.14", 100),
        (EMPTY, *([0] * 11)),
    ]
    assert actual == [(day, *map(Decimal, metrics)) for day, *metrics in expected]
    abc = published.abc("resumo", ["faturamento_produtos"], DAY, EMPTY)
    assert Decimal(abc["rows"][0][0]) == sum(r[5] for r in actual)
    itens = published.query(
        "BI_Itens",
        ["quantidade", "receita_item"],
        DAY,
        EMPTY,
        [],
        {"quantidade": "sum", "receita_item": "sum"},
    )
    assert list(map(Decimal, itens["rows"][0])) == [5, Decimal("85.01")]
    assert published.query(
        "BI_LTV_Clientes", ["pedidos", "ltv_observado"], "", "", [], {}
    )["rows"] == [["1", "77.89"]]
    assert (
        published.query("BI_Vendas", fields, "2026-04-14", "2026-04-14", [], {})["rows"]
        == []
    )


@pytest.mark.parametrize(
    "condition",
    ["canonical", "conflicting_total", "no_canonical_key", "conflicting_id"],
)
def test_two_operational_aliases_require_unambiguous_financial_evidence(
    store, condition
):
    rev = begin(store)
    main = row(
        "BI_Pedidos",
        pedido_id="601",
        pedido_chave="alternativa-1"
        if condition == "no_canonical_key"
        else "FARMALIDER:601",
        cliente_chave="cliente-sintetico",
        data=DAY,
        venda_valida="1",
        pedido_valor="11.25",
        pedido_faturamento_total="11.25",
        pedido_frete="1.00",
        pedido_valor_produtos="10.25",
    )
    other = dict(main, pedido_chave="alternativa-2")
    if condition == "conflicting_id":
        main["pedido_chave"] = "FARMALIDER:602"
    if condition == "conflicting_total":
        other.update(
            pedido_valor_produtos="10.20",
            pedido_valor="11.20",
            pedido_faturamento_total="11.20",
        )
    batch(store, rev, "BI_Pedidos", [main, other])
    finish(store, rev)
    reader = Reader(DSN, "homologacao", "FARMA")
    fields = ["pedido_id", "pedido_faturamento_total"]
    aggregates = {"pedido_id": "count", "pedido_faturamento_total": "sum"}
    if condition == "canonical":
        assert reader.query("BI_Pedidos", fields, DAY, DAY, [], aggregates)["rows"] == [
            [1, "11.25"]
        ]
    else:
        # COUNT sozinho também deve se recusar a exibir uma conclusão ambígua.
        with pytest.raises(StorageError, match="DS_BI_PEDIDO_OPERACIONAL_AMBIGUO"):
            reader.query(
                "BI_Pedidos", ["pedido_id"], DAY, DAY, [], {"pedido_id": "count"}
            )


def test_missing_freight_and_item_quantity_cannot_be_displayed_as_known_daily_sums(
    published, store
):
    # Testa a leitura de uma projeção antiga incompleta, sem aprovar outro READY.
    # 501 ainda contém produtos, frete e quantidades conhecidos neste mesmo dia.
    sale = opaque_key("venda", "FARMALIDER:505")
    with store.connect() as conn:
        for table, field in [
            ("BI_Clientes_Vendas", "frete"),
            ("BI_Itens", "quantidade"),
        ]:
            result = conn.execute(
                "UPDATE farma.nf_atuais SET registro=registro - %s::text "
                "WHERE tabela=%s AND registro->>'venda_chave'=%s",
                (field, table, sale),
            )
            assert result.rowcount == 1
        result = conn.execute(
            "SELECT faturamento_produtos, faturamento_frete, unidades_vendidas "
            "FROM farma.ds_bi_vendas WHERE data=%s",
            (DAY,),
        ).fetchone()
        assert result == {
            "faturamento_produtos": Decimal("72.90"),
            "faturamento_frete": None,
            "unidades_vendidas": None,
        }
        conn.rollback()


def test_reader_rejects_partial_freight_over_period_but_keeps_known_measures(
    published, store
):
    sale = opaque_key("venda", "FARMALIDER:505")
    rev = begin(store)
    record = next(
        r for r in store.rows("BI_Clientes_Vendas")["rows"] if r["venda_chave"] == sale
    )
    batch(store, rev, "BI_Clientes_Vendas", [dict(record, frete="")])
    finish(store, rev)
    for aggregation in ({}, {"faturamento_frete": "sum"}):
        with pytest.raises(StorageError, match="DS_BI_VENDAS_INCOMPLETA"):
            published.query(
                "BI_Vendas", ["faturamento_frete"], DAY, NEXT, [], aggregation
            )
    products = published.query(
        "BI_Vendas",
        ["faturamento_produtos"],
        DAY,
        NEXT,
        [],
        {"faturamento_produtos": "sum"},
    )
    assert Decimal(products["rows"][0][0]) == Decimal("85.01")
    assert published.query(
        "BI_Vendas",
        ["faturamento_frete"],
        "2026-05-01",
        "2026-05-01",
        [],
        {"faturamento_frete": "sum"},
    )["rows"] == [[None]]
