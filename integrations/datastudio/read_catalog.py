"""Projeções do relatório, separadas do contrato Windows de armazenamento."""

from copy import deepcopy
from typing import LiteralString

from ds_backend.contract import REGISTRY, StorageError
from integrations.datastudio.weni_daily import COLUMNS, FIELDS, TABLE

READ_REGISTRY = deepcopy(REGISTRY)
READ_REGISTRY[TABLE] = dict(
    public=True,
    columns=COLUMNS,
    period="data",
    segment="FARMA",
    types={
        f: ("date" if f == "data" else "number" if f in FIELDS else "text")
        for f in COLUMNS
    },
)
PUBLIC_SUMMARY = "BI_Publico_Resumo"
PUBLIC_DIMENSIONS = ("cidade", "canal", "idade", "idade_informada")
PUBLIC_METRICS = {
    "contatos": "Contatos",
    "compra_identificada": "Com compra identificada",
    "sem_compra_identificada": "Sem compra identificada",
    "contatos_idade_informada": "Contatos com idade informada",
    "contatos_sem_cidade": "Contatos sem cidade",
}
READ_REGISTRY[PUBLIC_SUMMARY] = dict(
    public=True,
    segment="FARMA",
    optional=True,
    columns=[*PUBLIC_DIMENSIONS, *PUBLIC_METRICS],
    period=None,
    types={
        field: "text" if field in ("cidade", "canal") else "number"
        for field in (*PUBLIC_DIMENSIONS, *PUBLIC_METRICS)
    },
    dimensions=["idade", "idade_informada"],
    labels=PUBLIC_METRICS,
    metric_kinds=dict.fromkeys(PUBLIC_METRICS, "sum"),
)
PROJECTIONS = {
    "Metricas_Diarias": (
        "data tipo_atribuicao anuncio_id anuncio_titulo contatos",
        "contatos",
    ),
    "Metricas_Vendas": (
        "data pedidos pedidos_confirmados_api clientes_compradores unidades_vendidas faturamento_produtos faturamento_frete faturamento faturamento_confirmado_api",
        "pedidos pedidos_confirmados_api clientes_compradores unidades_vendidas faturamento_produtos faturamento_frete faturamento faturamento_confirmado_api",
    ),
    "Pedidos_FarmaLider": (
        "pedido_chave pedido_id contact_uuid data origem_pedido status_confirmacao status_validacao farmalider_status_pedido farmalider_forma_pagamento",
        "",
    ),
    "Itens_Pedidos_FarmaLider": (
        "item_chave pedido_chave data produto_codigo produto_nome quantidade valor_unitario valor_total",
        "quantidade valor_unitario valor_total",
    ),
}
for name, (fields, numbers) in PROJECTIONS.items():
    spec = READ_REGISTRY[name]
    spec["public"] = True
    spec["read_columns"] = fields.split()
    for field in numbers.split():
        spec["types"][field] = "number"


# Campo do relatório ds72, comprovado no editor pelo Work. Não é a regra
# financeira global: os estados abertos continuam preservados no armazenamento.
ELIGIBLE_FIELD = "calc_gf73fvq57d"
READ_REGISTRY["Pedidos_FarmaLider"]["read_columns"].append(ELIGIBLE_FIELD)
READ_REGISTRY["Pedidos_FarmaLider"]["types"][ELIGIBLE_FIELD] = "text"
READ_REGISTRY["Pedidos_FarmaLider"]["labels"] = {ELIGIBLE_FIELD: "Venda elegível"}
DERIVED_SQL: dict[tuple[str, str], LiteralString] = {
    ("Pedidos_FarmaLider", ELIGIBLE_FIELD): """CASE
        WHEN registro ->> 'status_confirmacao' = 'CONFIRMADO_API'
        AND registro ->> 'status_validacao' IN ('OK', 'ATENÇÃO_TOTAL_DIVERGENTE')
        AND registro ->> 'farmalider_status_pedido' IN ('4', '1', '2')
        AND registro ->> 'farmalider_forma_pagamento' != '0'
        THEN 'Sim' ELSE 'Não' END""",
}


_PRODUCT = {
    "produto_codigo",
    "produto_nome",
    "quantidade",
    "receita_item",
    "participacao_acumulada",
    "registros",
}
PRODUCT_FIELDS = {
    "ranking": _PRODUCT,
    "receita": _PRODUCT | {"posicao_receita_top5"},
    "unidades": _PRODUCT | {"posicao_unidades_top5"},
    "resumo": {"produtos_distintos_periodo", "quantidade", "receita_item", "registros"},
    "nomes": {"produto_nome", "registros"},
}


def read_contract(name):
    if name not in READ_REGISTRY:
        raise StorageError("DS_TABELA_NAO_AUTORIZADA")
    return READ_REGISTRY[name]
