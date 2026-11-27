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

NoturnoScenario = Literal[
    "normal", "dados_incompletos", "rede_temporaria", "resposta_incerta",
    "fonte_essencial_incompleta",
    "leitura_real_amostral",
    "meta_recuperacao",
    "meta_consulta_direta_falha",
    "reserva_isolada", "reserva_anuncios_incompletos", "recompra_resposta_perdida",
]
NOTURNO_SCENARIOS = frozenset(get_args(NoturnoScenario))
NoturnoStage = Literal[
    "atualizacao_weni", "analytics", "publicacao", "recompra", "analytics_final"
]
NOTURNO_STAGES = get_args(NoturnoStage)


def noturno_stages(completed, task_state):
    """Projeção da fila persistida para o n8n e a Central."""
    current = next(
        (number for number in range(1, len(NOTURNO_STAGES) + 1) if number not in completed),
        None,
    )
    return [
        {
            "etapa": name,
            "estado": "concluida" if number in completed else
                      task_state if number == current else "pendente",
        }
        for number, name in enumerate(NOTURNO_STAGES, start=1)
    ]
