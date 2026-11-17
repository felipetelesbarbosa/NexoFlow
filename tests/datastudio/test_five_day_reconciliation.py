"""Concilia no mesmo READY dias com exclusão, lacunas e revisões de valores."""

from collections import defaultdict
from decimal import Decimal

import pytest

from integrations.datastudio.reader import Reader
from looker_bi import opaque_key
from tests.datastudio.test_contract import row
from tests.datastudio.test_ds_database import DSN, batch, begin, finish
from tests.datastudio.test_ds_database import store as store

pytestmark = pytest.mark.skipif(not DSN, reason="PostgreSQL descartável")


def money(cents):
    return format(Decimal(cents).scaleb(-2), ".2f")


def verify_five_days(store, days, product_deltas, duplicate_total, duplicate_freight):
    first, excluded_day, three_missing, revised_day, one_missing = days
    short, excluded, missing_three, revised, missing_one = product_deltas
    base = 1011
    duplicated_products = duplicate_total - duplicate_freight
    third, rest = divmod(-missing_three, 3)
    # dia, id oficial fictício, produtos no operacional, produtos no histórico, frete.
    # None representa ausência comprovada de uma linha nessa origem.
    orders = [
        (first, "901", duplicated_products, duplicated_products, duplicate_freight),
        (first, "902", base, base - short, 0),
        (excluded_day, "903", base, base, 0),
        (excluded_day, "904", excluded, None, 0),
        (three_missing, "905", base, base, 0),
        (three_missing, "906", None, third, 0),
        (three_missing, "907", None, third, 0),
        (three_missing, "908", None, third + rest, 0),
        (revised_day, "909", base, base - revised, 0),
        (one_missing, "910", base, None, 0),
        (one_missing, "911", None, -missing_one, 0),
    ]
    records = defaultdict(list)
    operational_days = {day: [0, 0, 0] for day in days}
    history_ltv = []
    owner = opaque_key("farmalider", "cliente-sintetico")
    for day, oid, old, current, fee in orders:
        key = "FARMALIDER:" + oid
        sale = opaque_key("venda", key)
        if old is not None:
            operational_days[day][0] += 1
            operational_days[day][1] += old
            operational_days[day][2] += fee
            header = row(
                "BI_Pedidos",
                pedido_chave=key,
                pedido_id=oid,
                data=day,
                cliente_chave=owner,
                venda_valida="1",
                pedido_valor_produtos=money(old),
                pedido_frete=money(fee),
                pedido_valor=money(old + fee),
                pedido_faturamento_total=money(old + fee),
            )
            records["BI_Pedidos"].append(header)
            if oid == "901":
                records["BI_Pedidos"].append(dict(header, pedido_chave="legado-901"))
            records["BI_Clientes_Vendas"].append(
                row(
                    "BI_Clientes_Vendas",
                    venda_chave=sale,
                    cliente_chave=owner,
                    data=day,
                    pedidos="1",
                    faturamento_produtos=money(old),
                    frete=money(fee),
                    faturamento=money(old + fee),
                )
            )
            records["BI_Itens"].append(
                row(
                    "BI_Itens",
                    item_chave=oid,
                    venda_chave=sale,
                    cliente_chave=owner,
                    data=day,
                    quantidade="1",
                    receita_item=money(old),
                    produto_codigo="0123",
                    sku_informado="1",
                )
            )
        if current is not None:
            history_ltv.append(current + fee)
            records["Historico_Pedidos"].append(
                row(
                    "Historico_Pedidos",
                    chave="FARMA:" + oid,
                    segmento="FARMA",
                    pedido_id=oid,
                    cliente_id="cliente-sintetico",
                    data=day,
                    estado="valido",
                    vigente="Sim",
                    produtos=money(current),
                    frete=money(fee),
                    faturamento=money(current + fee),
                )
            )
            records["Historico_Itens"].append(
                row(
                    "Historico_Itens",
                    chave="FARMA:" + oid + ":1",
                    segmento="FARMA",
                    pedido_id=oid,
                    item_id="1",
                    quantidade="1",
                    valor=money(current),
                    sku="0123",
                    frete="Não",
                    estado="valido",
                    vigente="Sim",
                )
            )

    records["Exclusoes_Publicacao"].append(
        row("Exclusoes_Publicacao", segmento="FARMA", pedido_id="904")
    )
    records["BI_LTV_Clientes"].append(
        row(
            "BI_LTV_Clientes",
            chave="FARMA:cliente-sintetico",
            segmento="FARMA",
            cliente_id="cliente-sintetico",
            pedidos=str(len(history_ltv)),
            ltv_observado=money(sum(history_ltv)),
            vigente="Sim",
        )
    )
    for day, (num, products, fee) in operational_days.items():
        records["BI_Vendas"].append(
            row(
                "BI_Vendas",
                data=day,
                pedidos=str(num),
                faturamento_produtos=money(products),
                faturamento_frete=money(fee),
                faturamento_total=money(products + fee),
            )
        )
    rev = begin(store)
    for table, rows in records.items():
        batch(store, rev, table, rows)
    receipt = finish(store, rev)
    reader = Reader(DSN, "homologacao", "FARMA")

    # Controles independentes das projeções e da planilha diária recebida.
    expected = [
        (2, duplicated_products + base - short, duplicate_freight),
        (1, base, 0),
        (4, base - missing_three, 0),
        (1, base - revised, 0),
        (2, base - missing_one, 0),
    ]
    physical = {r["data"]: r for r in store.rows("BI_Vendas")["rows"]}
    assert len(physical) == len(expected)
    for day, (count, products, fee), delta_count, delta_products in zip(
        days, expected, (0, 1, -3, 0, -1), product_deltas, strict=True
    ):
        raw = physical[day]
        assert int(raw["pedidos"]) - count == delta_count
        assert Decimal(raw["faturamento_produtos"]) * 100 - products == delta_products
        assert Decimal(raw["faturamento_frete"]) * 100 - fee == 0

        result = reader.query(
            "BI_Vendas",
            [
                "pedidos",
                "faturamento_produtos",
                "faturamento_frete",
                "faturamento_total",
            ],
            day,
            day,
            [],
            {},
        )
        assert result["version"] == receipt["version"]
        assert [Decimal(n) for n in result["rows"][0]] == [
            count,
            Decimal(money(products)),
            Decimal(money(fee)),
            Decimal(money(products + fee)),
        ]
        assert len(result["rows"]) == 1
        units, items = reader.query(
            "BI_Itens",
            ["quantidade", "receita_item"],
            day,
            day,
            [],
            {"quantidade": "sum", "receita_item": "sum"},
        )["rows"][0]
        assert Decimal(units) == count and Decimal(items) * 100 == products
        abc = reader.abc("resumo", ["faturamento_produtos"], day, day)
        assert (
            abc["version"] == receipt["version"]
            and Decimal(abc["rows"][0][0]) * 100 == products
        )
        headers = reader.query(
            "BI_Pedidos",
            ["pedido_id", "pedido_frete", "pedido_faturamento_total"],
            day,
            day,
            [{"field": "venda_valida", "values": ["1"]}],
            {},
        )["rows"]
        assert len(headers) == len({r[0] for r in headers}) == count
        assert sum(Decimal(r[1]) for r in headers) * 100 == fee
        assert sum(Decimal(r[2]) for r in headers) * 100 == products + fee
        sales = reader.query(
            "BI_Clientes_Vendas",
            ["venda_chave", "faturamento_produtos", "frete", "faturamento"],
            day,
            day,
            [],
            {},
        )["rows"]
        assert len(sales) == len({r[0] for r in sales}) == count
        assert [sum(Decimal(r[c]) for r in sales) * 100 for c in (1, 2, 3)] == [
            products,
            fee,
            products + fee,
        ]

    original = [r for r in store.rows("BI_Pedidos")["rows"] if r["pedido_id"] == "901"]
    assert len(original) == 2
    assert (
        sum(Decimal(r["pedido_faturamento_total"]) for r in original) * 100
        == 2 * duplicate_total
    )
    assert (
        sum(Decimal(r["pedido_frete"]) for r in original) * 100 == 2 * duplicate_freight
    )
    projected = reader.query(
        "BI_Pedidos",
        ["pedido_faturamento_total", "pedido_frete"],
        first,
        first,
        [{"field": "pedido_id", "values": ["901"]}],
        {},
    )["rows"]
    assert projected == [[money(duplicate_total), money(duplicate_freight)]]
    expected_period = sum(products for _, products, _ in expected)
    abc = reader.abc("resumo", ["faturamento_produtos"], days[0], days[-1])
    assert Decimal(abc["rows"][0][0]) * 100 == expected_period
    assert store.inspect(rev)["receipt"] == receipt


def test_five_daily_differences_and_independent_duplicate(store):
    verify_five_days(
        store,
        ("2024-02-01", "2024-02-02", "2024-02-03", "2024-02-04", "2024-02-05"),
        (-379, 54003, -203, -1201, -852),
        1203,
        154,
    )
