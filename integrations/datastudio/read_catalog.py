"""Projeções do relatório, separadas do contrato Windows de armazenamento."""

from copy import deepcopy
from typing import LiteralString

from ds_backend.contract import REGISTRY, StorageError

READ_REGISTRY = deepcopy(REGISTRY)
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


def read_contract(name):
    if name not in READ_REGISTRY:
        raise StorageError("DS_TABELA_NAO_AUTORIZADA")
    return READ_REGISTRY[name]
