"""Projeções do relatório, separadas do contrato Windows de armazenamento."""

from copy import deepcopy

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


def read_contract(name):
    if name not in READ_REGISTRY:
        raise StorageError("DS_TABELA_NAO_AUTORIZADA")
    return READ_REGISTRY[name]
