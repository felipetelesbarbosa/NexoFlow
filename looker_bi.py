"""Tabelas comerciais para o Looker; somente compras confirmadas e observadas."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from typing import Any

from analytics import (
    _bi_customer_age,
    _bi_float,
    _order_revenue_parts,
    _sales_order_is_valid,
    _to_decimal,
    bi_customer_key,
)
from pedido_utils import business_order_datetime

SCHEMAS = {
    "BI_Publico": [
        "contato_chave",
        "cliente_chave",
        "nome",
        "canal",
        "cidade",
        "estado",
        "genero",
        "idade",
        "idade_informada",
        "criado_em",
        "compra_identificada",
        "ultima_compra_identificada",
        "atualizado_em",
    ],
    "BI_Clientes": [
        "cliente_chave",
        "cliente",
        "pedidos_identificados",
        "faturamento_identificado",
        "ultima_compra_identificada",
        "atualizado_em",
    ],
    "BI_Clientes_Vendas": [
        "venda_chave",
        "cliente_chave",
        "cliente",
        "data",
        "pedidos",
        "faturamento_produtos",
        "frete",
        "faturamento",
        "atualizado_em",
    ],
    "BI_Itens": [
        "item_chave",
        "venda_chave",
        "cliente_chave",
        "data",
        "produto_codigo",
        "produto_nome",
        "categoria",
        "quantidade",
        "valor_unitario",
        "receita_item",
        "sku_informado",
        "atualizado_em",
    ],
    "BI_Produtos_ABC": [
        "periodo_inicio",
        "periodo_fim",
        "produto_codigo",
        "produto_nome",
        "categoria",
        "unidades",
        "receita_produtos",
        "pedidos",
        "ranking_receita",
        "ranking_unidades",
        "participacao_receita_pct",
        "participacao_acumulada_pct",
        "classe_abc",
        "abc_disponivel",
        "atualizado_em",
    ],
    "BI_Produtos_Juntos": [
        "periodo_inicio",
        "periodo_fim",
        "produto_a_codigo",
        "produto_a_nome",
        "produto_b_codigo",
        "produto_b_nome",
        "pedidos_juntos",
        "atualizado_em",
    ],
    "BI_KPIs_Periodo": [
        "periodo_inicio",
        "periodo_fim",
        "pedidos",
        "clientes_compradores",
        "faturamento_produtos",
        "frete",
        "faturamento",
        "ticket_medio",
        "pedidos_por_cliente",
        "receita_media_por_cliente",
        "skus_distintos",
        "participacao_top5_receita_pct",
        "clientes_com_multiplas_compras_identificadas",
        "comparacao_disponivel",
        "variacao_faturamento_pct",
        "variacao_pedidos_pct",
        "variacao_clientes_pct",
        "variacao_ticket_pct",
        "atualizado_em",
    ],
    "BI_Qualidade": [
        "atualizado_em",
        "historico_observado_desde",
        "historico_completo",
        "recompra_disponivel",
        "comparacao_disponivel",
        "primeira_compra_identificada",
        "ultima_compra_identificada",
        "contatos_base",
        "contatos_com_idade",
        "cobertura_idade_pct",
        "contatos_com_cidade",
        "contatos_com_genero",
        "itens_sem_sku",
        "itens_com_categoria",
        "anuncios_disponiveis",
        "custo_anuncios_disponivel",
        "motivo_historico",
    ],
}
DATE_COLUMNS = {
    "data",
    "criado_em",
    "ultima_compra_identificada",
    "primeira_compra_identificada",
    "periodo_inicio",
    "periodo_fim",
    "historico_observado_desde",
}
TEXT_COLUMNS = {
    "contato_chave",
    "cliente_chave",
    "venda_chave",
    "item_chave",
    "nome",
    "cliente",
    "canal",
    "cidade",
    "estado",
    "genero",
    "produto_codigo",
    "produto_nome",
    "categoria",
    "produto_a_codigo",
    "produto_a_nome",
    "produto_b_codigo",
    "produto_b_nome",
    "classe_abc",
    "atualizado_em",
    "motivo_historico",
}


def opaque_key(namespace: str, value: str) -> str:
    return hashlib.sha256(f"{namespace}:{value}".encode()).hexdigest()[:32]


def _date(value: Any) -> str:
    dt = business_order_datetime(str(value or ""))
    return dt.date().isoformat() if dt else ""


def _unique(records: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in records:
        identity = str(row.get(key) or "").strip()
        if not identity:
            continue
        if identity in result and result[identity] != row:
            raise ValueError(
                f"Registros conflitantes para {key}; publicação BI interrompida."
            )
        result[identity] = row
    return list(result.values())


def reporting_period(
    snapshot_date: str, start: str | None, end: str | None
) -> tuple[str, str]:
    finish = date.fromisoformat(end or snapshot_date)
    begin = date.fromisoformat(start) if start else finish - timedelta(days=29)
    if begin > finish or finish > date.fromisoformat(snapshot_date):
        raise ValueError("Período BI inválido: início após fim ou fim no futuro.")
    return begin.isoformat(), finish.isoformat()


def _rank_products(
    product_groups: dict[str, dict[str, Any]], start: str, end: str, updated_at: str
) -> tuple[list[list[Any]], list[tuple[str, dict[str, Any]]], Decimal]:
    rows: list[list[Any]] = []
    ranked = sorted(
        product_groups.items(), key=lambda pair: (-pair[1]["revenue"], pair[0])
    )
    total_products = sum((p["revenue"] for _, p in ranked), Decimal(0))
    abc_available = total_products > 0 and all(p["sku"] for _, p in ranked)
    unit_rank: dict[str, int] = {}
    previous_units: Decimal | None = None
    rank = 0
    for index, (key, p) in enumerate(
        sorted(ranked, key=lambda pair: (-pair[1]["units"], pair[0])), 1
    ):
        if p["units"] != previous_units:
            rank = index
        unit_rank[key], previous_units = rank, p["units"]
    cumulative = Decimal(0)
    previous_revenue: Decimal | None = None
    revenue_rank = 0
    group_class = ""
    for index, (key, p) in enumerate(ranked, 1):
        if p["revenue"] != previous_revenue:
            revenue_rank = index
            before = cumulative / total_products * 100 if total_products else Decimal(0)
            group_class = (
                ("A" if before < 80 else "B" if before < 95 else "C")
                if abc_available
                else ""
            )
        cumulative += p["revenue"]
        previous_revenue = p["revenue"]
        share = p["revenue"] / total_products * 100 if total_products else None
        accumulated = cumulative / total_products * 100 if total_products else None
        rows.append(
            [
                start,
                end,
                p["sku"],
                p["name"],
                p["category"],
                float(p["units"]),
                _bi_float(p["revenue"]),
                len(p["orders"]),
                revenue_rank,
                unit_rank[key],
                float(share) if share is not None else "",
                float(accumulated) if accumulated is not None else "",
                group_class,
                int(abc_available),
                updated_at,
            ]
        )
    return rows, ranked, total_products


def _product_pairs(
    products_by_order: dict[str, set[str]],
    names: dict[str, tuple[str, str]],
    start: str,
    end: str,
    updated_at: str,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    pairs: dict[tuple[str, str], int] = defaultdict(int)
    for skus in products_by_order.values():
        for pair in combinations(sorted(skus), 2):
            pairs[pair] += 1
    for (a, b), count in sorted(pairs.items(), key=lambda pair: (-pair[1], pair[0])):
        rows.append([start, end, a, names[a][1], b, names[b][1], count, updated_at])

    return rows


def _period_kpis(
    orders_by_key: dict[str, dict[str, Any]],
    period_items: list[dict[str, Any]],
    ranked: list[tuple[str, dict[str, Any]]],
    total_products: Decimal,
    start: str,
    end: str,
    updated_at: str,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    period_orders = [r for r in orders_by_key.values() if start <= r["bi_date"] <= end]
    buyer_counts: dict[str, int] = defaultdict(int)
    for row in period_orders:
        buyer_counts[row["bi_customer"]] += 1
    count, buyers = len(period_orders), len(buyer_counts)
    products_total = sum((r["bi_products"] for r in period_orders), Decimal(0))
    freight_total = sum((r["bi_freight"] for r in period_orders), Decimal(0))
    total = sum((r["bi_total"] for r in period_orders), Decimal(0))
    rows.append(
        [
            start,
            end,
            count,
            buyers,
            _bi_float(products_total),
            _bi_float(freight_total),
            _bi_float(total),
            _bi_float(total / count) if count else "",
            float(Decimal(count) / buyers) if buyers else "",
            _bi_float(total / buyers) if buyers else "",
            len({p["sku"] for p in period_items if p["sku"]}),
            float(
                sum((p["revenue"] for _, p in ranked[:5]), Decimal(0))
                / total_products
                * 100
            )
            if total_products
            else "",
            sum(n > 1 for n in buyer_counts.values()),
            0,
            "",
            "",
            "",
            "",
            updated_at,
        ]
    )
    return rows


def build_looker_tables(
    base_records: list[dict[str, str]],
    order_records: list[dict[str, str]],
    item_records: list[dict[str, str]],
    *,
    snapshot_date: str,
    updated_at: str,
    period_start: str | None = None,
    period_end: str | None = None,
    history_observed_since: str = "",
) -> dict[str, list[list[Any]]]:
    """ABC/compras juntas têm período explícito; fatos aceitam filtros livres.

    A API de último pedido não comprova cobertura completa, mesmo após várias
    coletas. Recompra e comparação completas continuam indisponíveis.
    """
    start, end = reporting_period(snapshot_date, period_start, period_end)
    tables: dict[str, list[list[Any]]] = {name: [] for name in SCHEMAS}
    base_by_uuid = {
        r.get("contact_uuid", ""): r for r in base_records if r.get("contact_uuid")
    }
    orders = [
        r for r in _unique(order_records, "pedido_chave") if _sales_order_is_valid(r)
    ]
    orders_by_key: dict[str, dict[str, Any]] = {}
    customer_orders: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in orders:
        order_date = _date(order.get("data_hora") or order.get("data"))
        if not order_date or order_date > snapshot_date:
            continue
        base = base_by_uuid.get(order.get("contact_uuid", ""), {})
        customer = bi_customer_key(order, base)
        if not customer:
            continue
        products, freight, total = _order_revenue_parts(order)
        row = {
            **order,
            "bi_date": order_date,
            "bi_customer": customer,
            "bi_name": str(
                order.get("cliente") or base.get("nome") or base.get("weni_name") or ""
            ).strip(),
            "bi_products": products,
            "bi_freight": freight,
            "bi_total": total,
        }
        orders_by_key[order["pedido_chave"]] = row
        customer_orders[customer].append(row)
        tables["BI_Clientes_Vendas"].append(
            [
                opaque_key("venda", order["pedido_chave"]),
                customer,
                row["bi_name"],
                order_date,
                1,
                _bi_float(products),
                _bi_float(freight),
                _bi_float(total),
                updated_at,
            ]
        )

    last_by_contact: dict[str, str] = {}
    buyer_contacts: set[str] = set()
    for row in orders_by_key.values():
        uuid = row.get("contact_uuid", "")
        buyer_contacts.add(uuid)
        last_by_contact[uuid] = max(last_by_contact.get(uuid, ""), row["bi_date"])
    for customer in sorted(customer_orders):
        history = sorted(
            customer_orders[customer], key=lambda r: (r["bi_date"], r["pedido_chave"])
        )
        tables["BI_Clientes"].append(
            [
                customer,
                history[-1]["bi_name"],
                len(history),
                _bi_float(sum((r["bi_total"] for r in history), Decimal(0))),
                history[-1]["bi_date"],
                updated_at,
            ]
        )
    ages = cities = genders = 0
    for uuid, base in sorted(base_by_uuid.items()):
        age = _bi_customer_age(base.get("idade"))
        city, gender = (
            str(base.get("cidade") or "").strip(),
            str(base.get("genero") or "").strip(),
        )
        ages += age != ""
        cities += bool(city)
        genders += bool(gender)
        public_customer = bi_customer_key({}, base)
        customer_history = customer_orders.get(public_customer, [])
        public_last = max(
            (r["bi_date"] for r in customer_history),
            default=last_by_contact.get(uuid, ""),
        )
        tables["BI_Publico"].append(
            [
                opaque_key("contato", uuid),
                public_customer,
                str(base.get("nome") or base.get("weni_name") or "").strip(),
                str(base.get("contact_canal_principal") or "outro"),
                city,
                str(base.get("estado") or ""),
                gender,
                age,
                int(age != ""),
                _date(base.get("weni_created_on")),
                int(bool(customer_history) or uuid in buyer_contacts),
                public_last,
                updated_at,
            ]
        )

    product_groups: dict[str, dict[str, Any]] = {}
    products_by_order: dict[str, set[str]] = defaultdict(set)
    names: dict[str, tuple[str, str]] = {}
    missing_sku = category_items = 0
    period_items: list[dict[str, Any]] = []
    for item in _unique(item_records, "item_chave"):
        order = orders_by_key.get(item.get("pedido_chave", ""))
        if order is None:
            continue
        sku = str(item.get("produto_codigo") or "").strip()
        name = str(item.get("produto_nome") or "").strip()
        category = str(item.get("categoria") or "").strip()
        quantity = _to_decimal(item.get("quantidade"), "quantidade")
        revenue = _to_decimal(item.get("valor_total"), "valor_total")
        unit = _to_decimal(item.get("valor_unitario"), "valor_unitario")
        if quantity <= 0 or revenue < 0 or unit < 0:
            raise ValueError("Item de venda com quantidade ou valor inválido.")
        missing_sku += not bool(sku)
        category_items += bool(category)
        tables["BI_Itens"].append(
            [
                opaque_key("item", item["item_chave"]),
                opaque_key("venda", order["pedido_chave"]),
                order["bi_customer"],
                order["bi_date"],
                sku,
                name,
                category,
                float(quantity),
                _bi_float(unit),
                _bi_float(revenue),
                int(bool(sku)),
                updated_at,
            ]
        )
        if not start <= order["bi_date"] <= end:
            continue
        period_items.append({"sku": sku, "revenue": revenue})
        # Sem SKU, não colapsar produtos de mesmo nome numa identidade inventada.
        product_key = sku or opaque_key("item_sem_sku", item["item_chave"])
        bucket = product_groups.setdefault(
            product_key,
            {
                "sku": sku,
                "name": name,
                "category": category,
                "last": "",
                "units": Decimal(0),
                "revenue": Decimal(0),
                "orders": set(),
            },
        )
        if (order["bi_date"], name) >= (bucket["last"], bucket["name"]):
            bucket.update(name=name, category=category, last=order["bi_date"])
        bucket["units"] += quantity
        bucket["revenue"] += revenue
        bucket["orders"].add(order["pedido_chave"])
        if sku:
            products_by_order[order["pedido_chave"]].add(sku)
            if (order["bi_date"], name) > names.get(sku, ("", "")):
                names[sku] = (order["bi_date"], name)

    tables["BI_Produtos_ABC"], ranked, total_products = _rank_products(
        product_groups, start, end, updated_at
    )
    tables["BI_Produtos_Juntos"] = _product_pairs(
        products_by_order, names, start, end, updated_at
    )
    tables["BI_KPIs_Periodo"] = _period_kpis(
        orders_by_key, period_items, ranked, total_products, start, end, updated_at
    )
    observed_dates = [r["bi_date"] for r in orders_by_key.values()]
    tables["BI_Qualidade"].append(
        [
            updated_at,
            history_observed_since,
            0,
            0,
            0,
            min(observed_dates) if observed_dates else "",
            max(observed_dates) if observed_dates else "",
            len(base_by_uuid),
            ages,
            100 * ages / len(base_by_uuid) if base_by_uuid else "",
            cities,
            genders,
            missing_sku,
            category_items,
            int(
                any(
                    r.get("primeiro_anuncio_id") or r.get("ultimo_anuncio_id")
                    for r in base_records
                )
            ),
            0,
            "A API retorna somente o último pedido. O histórico acumula compras identificadas nas coletas; compras nunca capturadas e cobertura completa não são comprovadas.",
        ]
    )
    return tables
