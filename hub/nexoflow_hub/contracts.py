"""Contratos fechados de homologação, sem destinos ou credenciais."""

from typing import Literal, get_args

Scenario = Literal[
    "normal",
    "dados_incompletos",
    "sem_pedido",
    "segmento_desconhecido",
    "segmento_divergente",
    "cancelado",
    "pagamento_cancelado",
    "itens_vazios",
    "frete_divergente",
    "identidade_divergente",
    "recusa",
    "optout",
    "compra_recente",
    "retroativo",
    "rede_temporaria",
    "autenticacao",
    "resposta_incerta",
]
SCENARIOS = frozenset(get_args(Scenario))
